export const config = { runtime: 'edge' };

export default async function handler(req) {
  if (req.method === 'OPTIONS') {
    return new Response(null, {
      headers: {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'POST',
        'Access-Control-Allow-Headers': 'Content-Type',
      }
    });
  }

  try {
    const { message, history } = await req.json();

    const system = "You are Afghan AI, a smart and knowledgeable assistant. Answer ANY question on any topic: history, geography, science, news, culture, health, cooking, sports, technology, religion, politics, and more. Always reply in the SAME language the user writes in — if they write in Dari reply in Dari, if Pashto reply in Pashto, if Uzbek reply in Uzbek, if English reply in English. Be accurate, friendly, and clear. Never mention where your information comes from. You are simply Afghan AI.";

    const messages = [
      { role: 'system', content: system },
      ...(history || []).slice(-8),
      { role: 'user', content: message }
    ];

    const r = await fetch('https://api.groq.com/openai/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${process.env.GROQ_API_KEY}`
      },
      body: JSON.stringify({
        model: 'llama3-8b-8192',
        messages,
        max_tokens: 600,
        temperature: 0.7
      })
    });

    const d = await r.json();
    const reply = d?.choices?.[0]?.message?.content;
    return new Response(JSON.stringify({ reply: reply || null }), {
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' }
    });
  } catch (e) {
    return new Response(JSON.stringify({ reply: null }), {
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' }
    });
  }
}
