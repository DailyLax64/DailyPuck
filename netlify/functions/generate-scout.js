exports.handler = async function(event, context) {
    if (event.httpMethod !== "POST") {
        return { statusCode: 405, body: "Method Not Allowed" };
    }

    const apiKey = process.env.GEMINI_API_KEY;
    if (!apiKey) {
        return { 
            statusCode: 500, 
            body: JSON.stringify({ error: "GEMINI_API_KEY is not configured in Netlify environment variables." }) 
        };
    }

    try {
        const payload = JSON.parse(event.body || "{}");
        const prompt = payload.prompt;

        // Current active models in order of speed and capability
        const candidateModels = [
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-2.5-flash"
        ];

        let lastErr = null;
        for (const model of candidateModels) {
            try {
                const response = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        contents: [{ parts: [{ text: prompt }] }],
                        generationConfig: { response_mime_type: "application/json" }
                    })
                });

                if (!response.ok) {
                    const errJson = await response.json().catch(() => ({}));
                    lastErr = errJson.error?.message || `HTTP ${response.status} on ${model}`;
                    continue;
                }

                const data = await response.json();
                const candidate = data.candidates?.[0];
                const parts = candidate?.content?.parts || [];
                const textPart = parts.find(p => p.text && !p.thought) || parts[parts.length - 1];
                let rawText = textPart?.text || "[]";
                rawText = rawText.replace(/```json/g, "").replace(/```/g, "").trim();

                return {
                    statusCode: 200,
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ cards: JSON.parse(rawText) })
                };
            } catch (err) {
                lastErr = err.message;
            }
        }

        throw new Error(lastErr || "All Gemini models are momentarily busy.");
    } catch (err) {
        return {
            statusCode: 500,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ error: err.message })
        };
    }
};
