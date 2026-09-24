/**
 * Netlify Serverless Function: generate-scout.js
 * Proxy endpoint to call Google Gemini API securely without exposing API keys.
 */

exports.handler = async function (event, context) {
    // 1. Handle CORS preflight
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

        // Active Gemini models supporting JSON generation (gemini-2.5 is retired for new keys)
        const candidateModels = [
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-2.0-flash"
        ];

        let lastErr = null;

        for (const model of candidateModels) {
            try {
                const response = await fetch(
                    `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`,
                    {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            contents: [
                                {
                                    parts: [{ text: prompt }]
                                }
                            ],
                            generationConfig: {
                                responseMimeType: "application/json"
                            }
                        })
                    }
                );

                if (!response.ok) {
                    const errJson = await response.json().catch(() => ({}));
                    lastErr = errJson.error?.message || `HTTP ${response.status} on ${model}`;
                    console.warn(`[Gemini API] Model ${model} failed: ${lastErr}`);
                    continue;
                }

                const data = await response.json();
                const candidate = data.candidates?.[0];
                const parts = candidate?.content?.parts || [];

                // Filter out internal thinking steps and extract the final text part
                const textPart = parts.find(p => p.text && !p.thought) || parts[parts.length - 1];
                let rawText = textPart?.text || "[]";

                // Strip markdown backticks if returned
                rawText = rawText.replace(/```json/gi, "").replace(/```/g, "").trim();

                let parsed;
                try {
                    parsed = JSON.parse(rawText);
                } catch (parseErr) {
                    lastErr = `Failed to parse JSON response from ${model}`;
                    continue;
                }

                // Standardize cards structure whether model returns array or object
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
                console.error(`[Gemini API] Request exception on ${model}:`, err);
            }
        }

        throw new Error(lastErr || "All candidate Gemini models failed to generate content.");

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
