import wolframalpha

# Replace with your App ID
APP_ID = "6WYRLA-YXTJ5JXJWW"
client = wolframalpha.Client(APP_ID)

# Try a simple math query
query = "integrate x^2 from 0 to 1"
result = client.query(query)

# Extract and print the result
answer = next(result.results).text
print("✅ Wolfram Answer:", answer)
