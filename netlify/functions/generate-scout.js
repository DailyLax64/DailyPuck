/**
 * Netlify Serverless Function: generate-scout.js
 * Proxy calling Gemini API with explicit quota detection.
 */

exports.handler = async function (event, context) {
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

        const candidateModels = [
            {
                name: "gemini-3.5-flash-lite",
                config: { responseMimeType: "application/json" }
            },
            {
                name: "gemini-3.6-flash",
                config: {
                    responseMimeType: "application/json",
                    thinkingConfig: { thinkingLevel: "low" }
                }
            }
        ];

        let lastErr = null;
        let isQuota = false;

        for (const { name: model, config: genConfig } of candidateModels) {
            try {
                const apiUrl = `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`;

                const response = await fetch(apiUrl, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    signal: AbortSignal.timeout(6500),
                    body: JSON.stringify({
                        contents: [{ parts: [{ text: prompt }] }],
                        generationConfig: genConfig
                    })
                });

                if (!response.ok) {
                    const errJson = await response.json().catch(() => ({}));
                    const errMsg = errJson.error?.message || `HTTP ${response.status} on ${model}`;
                    lastErr = errMsg;

                    if (response.status === 429 || errMsg.toLowerCase().includes("quota")) {
                        isQuota = true;
                    }
                    continue;
                }

                const data = await response.json();
                const candidate = data.candidates?.[0];
                const parts = candidate?.content?.parts || [];

                const textPart = parts.find(p => p.text && !p.thought) || parts[parts.length - 1];
                let rawText = textPart?.text || "[]";

                rawText = rawText.replace(/```json/gi, "").replace(/```/g, "").trim();

                let parsed;
                try {
                    parsed = JSON.parse(rawText);
                } catch (parseErr) {
                    const match = rawText.match(/\[[\s\S]*\]/);
                    if (match) parsed = JSON.parse(match[0]);
                    else continue;
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
            }
        }

        return {
            statusCode: isQuota ? 429 : 502,
            headers: {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            body: JSON.stringify({
                error: lastErr || "AI models unavailable.",
                quotaExceeded: isQuota
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
