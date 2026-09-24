/**
 * Netlify Serverless Function: generate-scout.js
 * High-speed proxy with automatic quota failover across Gemini models.
 */

exports.handler = async function (event, context) {
    // 1. CORS Preflight
    if (event.httpMethod === "OPTIONS") {
        return {
            statusCode: 200,
            headers: {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Allow-Methods": "POST, OPTIONS"
            },
            body: ""
        };
    }

    if (event.httpMethod !== "POST") {
        return {
            statusCode: 405,
            headers: {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            body: JSON.stringify({ error: "Method Not Allowed. Use POST." })
        };
    }

    const apiKey = process.env.GEMINI_API_KEY;
    if (!apiKey) {
        return {
            statusCode: 500,
            headers: {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            body: JSON.stringify({ error: "GEMINI_API_KEY is not configured in Netlify environment variables." })
        };
    }

    try {
        const payload = JSON.parse(event.body || "{}");
        const prompt = payload.prompt;

        if (!prompt) {
            return {
                statusCode: 400,
                headers: {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*"
                },
                body: JSON.stringify({ error: "Missing required 'prompt' parameter in request body." })
            };
        }

        // Models with separate free-tier quota pools. If one hits 429, we immediately try the next.
        const candidateModels = [
            {
                name: "gemini-3.6-flash",
                config: {
                    responseMimeType: "application/json",
                    thinkingConfig: { thinkingLevel: "low" }
                }
            },
            {
                name: "gemini-2.0-flash",
                config: {
                    responseMimeType: "application/json"
                }
            },
            {
                name: "gemini-2.0-flash-lite",
                config: {
                    responseMimeType: "application/json"
                }
            }
        ];

        let lastErr = null;
        let retrySeconds = 30;

        for (const { name: model, config: genConfig } of candidateModels) {
            try {
                const apiUrl = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`;

                const response = await fetch(apiUrl, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    signal: AbortSignal.timeout(6000), // 6s timeout per model to stay well within Netlify's 10s limit
                    body: JSON.stringify({
                        contents: [{ parts: [{ text: prompt }] }],
                        generationConfig: genConfig
                    })
                });

                if (!response.ok) {
                    const errJson = await response.json().catch(() => ({}));
                    const errMsg = errJson.error?.message || `HTTP ${response.status} on ${model}`;
                    lastErr = errMsg;

                    // If rate-limited, parse wait time and try the next candidate model
                    if (response.status === 429) {
                        const match = errMsg.match(/retry in ([0-9.]+)s/i);
                        if (match) retrySeconds = Math.ceil(parseFloat(match[1]));
                        console.warn(`[Gemini API] ${model} quota reached. Failing over to next model...`);
                        continue;
                    }

                    console.warn(`[Gemini API] ${model} returned error: ${errMsg}`);
                    continue;
                }

                const data = await response.json();
                const candidate = data.candidates?.[0];
                const parts = candidate?.content?.parts || [];

                // Filter out reasoning thoughts and get output text
                const textPart = parts.find(p => p.text && !p.thought) || parts[parts.length - 1];
                let rawText = textPart?.text || "[]";

                rawText = rawText.replace(/```json/gi, "").replace(/```/g, "").trim();

                let parsed;
                try {
                    parsed = JSON.parse(rawText);
                } catch (parseErr) {
                    const match = rawText.match(/\[[\s\S]*\]/);
                    if (match) {
                        parsed = JSON.parse(match[0]);
                    } else {
                        throw new Error("Could not parse AI response into structured JSON.");
                    }
                }

                const cards = Array.isArray(parsed) ? parsed : (parsed.cards || []);

                return {
                    statusCode: 200,
                    headers: {
                        "Content-Type": "application/json",
                        "Access-Control-Allow-Origin": "*"
                    },
                    body: JSON.stringify({ cards })
                };

            } catch (err) {
                lastErr = err.message;
                console.warn(`[Gemini API] Request exception on ${model}: ${err.message}`);
            }
        }

        // If all candidate models are exhausted
        return {
            statusCode: 429,
            headers: {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            body: JSON.stringify({
                error: lastErr || "Quota exceeded across all Gemini models.",
                retryAfter: retrySeconds
            })
        };

    } catch (err) {
        return {
            statusCode: 500,
            headers: {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            body: JSON.stringify({ error: err.message })
        };
    }
};
