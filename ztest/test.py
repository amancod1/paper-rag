from openai import OpenAI


KEY = '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'

client = OpenAI(api_key=KEY)
model = 'gpt-3.5-turbo'

response = client.chat.completions.create(
    model=model,
    messages=[
        {'role': 'user', 'content': '사과는 무슨 색이야?'}
    ]
)

print(response.choices[0].message.content)


