/**
 * Netlify Serverless Function: generate-scout.js
 * High-speed proxy calling Gemini 3.6 Flash with minimal thinking latency.
 */

exports.handler = async function (event, context) {
    // Handle CORS preflight
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
                    thinkingConfig: {
                        thinkingLevel: "MINIMAL"
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

        // Exclude internal thoughts and retrieve final JSON text
        const textPart = parts.find(p => p.text && !p.thought) || parts[parts.length - 1];
        let rawText = textPart?.text || "[]";

        // Strip any residual code fences
        rawText = rawText.replace(/```json/gi, "").replace(/```/g, "").trim();

        let parsed;
        try {
            parsed = JSON.parse(rawText);
        } catch (parseErr) {
            throw new Error("Model response could not be parsed as JSON: " + rawText.slice(0, 100));
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
