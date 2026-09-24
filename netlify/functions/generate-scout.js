/**
 * Netlify Serverless Function: generate-scout.js
 * Direct single-hop proxy calling gemini-3.6-flash with low thinking latency.
 */

exports.handler = async function (event, context) {
    // 1. Handle CORS Preflight
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

        // Direct single call to Google's designated Gemini 3.6 Flash endpoint
        const apiUrl = `https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key=${apiKey}`;

        const response = await fetch(apiUrl, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                contents: [
                    {
                        parts: [{ text: prompt }]
                    }
                ],
                generationConfig: {
                    responseMimeType: "application/json",
                    maxOutputTokens: 1000,
                    thinkingConfig: {
                        thinkingLevel: "low"
                    }
                }
            })
        });

        if (!response.ok) {
            const errJson = await response.json().catch(() => ({}));
            const errMsg = errJson.error?.message || `Google API error HTTP ${response.status}`;
            throw new Error(errMsg);
        }

        const data = await response.json();
        const candidate = data.candidates?.[0];
        const parts = candidate?.content?.parts || [];

        // Isolate the final output text (ignoring thinking tokens)
        const textPart = parts.find(p => p.text && !p.thought) || parts[parts.length - 1];
        let rawText = textPart?.text || "[]";

        // Clean any residual markdown formatting
        rawText = rawText.replace(/```json/gi, "").replace(/```/g, "").trim();

        let parsed;
        try {
            parsed = JSON.parse(rawText);
        } catch (parseErr) {
            // Regex fallback if wrapped in extra text
            const match = rawText.match(/\[\s*\{[\s\S]*\}\s*\]/);
            if (match) {
                parsed = JSON.parse(match[0]);
            } else {
                throw new Error("Could not parse AI response into JSON cards.");
            }
        }

        // Standardize output format
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
