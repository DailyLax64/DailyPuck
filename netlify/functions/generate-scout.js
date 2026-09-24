/**
 * Netlify Serverless Function: generate-scout.js
 * High-speed proxy calling Gemini Flash-Lite for sub-2-second JSON generation.
 */

exports.handler = async function (event, context) {
    // 1. CORS Preflight Support
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
                body: JSON.stringify({ error: "Missing required 'prompt' parameter." })
            };
        }

        // Fast-inference Flash-Lite models in order of speed and availability
        const candidateModels = [
            "gemini-3.1-flash-lite",
            "gemini-3.5-flash-lite",
            "gemini-flash-lite-latest",
            "gemini-3.6-flash"
        ];

        let lastErr = null;

        for (const model of candidateModels) {
            try {
                const apiUrl = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`;

                // 7.5-second internal safety abort to stay well below Netlify's 10s ceiling
                const response = await fetch(apiUrl, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    signal: AbortSignal.timeout(7500),
                    body: JSON.stringify({
                        contents: [
                            {
                                parts: [{ text: prompt }]
                            }
                        ],
                        generationConfig: {
                            responseMimeType: "application/json",
                            maxOutputTokens: 1000
                        }
                    })
                });

                if (!response.ok) {
                    const errJson = await response.json().catch(() => ({}));
                    lastErr = errJson.error?.message || `HTTP ${response.status} on ${model}`;
                    console.warn(`[Gemini API] ${model} failed: ${lastErr}`);
                    continue;
                }

                const data = await response.json();
                const candidate = data.candidates?.[0];
                const parts = candidate?.content?.parts || [];

                const textPart = parts.find(p => p.text && !p.thought) || parts[parts.length - 1];
                let rawText = textPart?.text || "[]";

                // Strip markdown backticks if present
                rawText = rawText.replace(/```json/gi, "").replace(/```/g, "").trim();

                let parsed;
                try {
                    parsed = JSON.parse(rawText);
                } catch (parseErr) {
                    const match = rawText.match(/\[\s*\{[\s\S]*\}\s*\]/);
                    if (match) {
                        parsed = JSON.parse(match[0]);
                    } else {
                        lastErr = `Could not parse JSON output from ${model}`;
                        continue;
                    }
                }

                let cards = [];
                if (Array.isArray(parsed)) {
                    cards = parsed;
                } else if (parsed && Array.isArray(parsed.cards)) {
                    cards = parsed.cards;
                } else if (parsed && typeof parsed === "object") {
                    cards = Object.entries(parsed).map(([k, v]) => ({
                        title: k,
                        data: typeof v === "string" ? v : JSON.stringify(v)
                    }));
                }

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
                console.warn(`[Gemini API] Attempt failed on ${model}: ${err.message}`);
            }
        }

        throw new Error(lastErr || "All Gemini candidate models timed out or failed.");

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
