import requests

url = "http://localhost:8000/api/leads/score/bulk/async"  # Ensure this matches the bulk score endpoint
headers = {
    "Authorization": "Bearer test-token",
    "Content-Type": "application/json"
}
body = {
    "leads": [
        {
            "lead_id": "12345",  # Example lead_id
            "lead_data": {
                "platform_presence": {
                    "platforms": ["Heureka", "Allegro"]
                },
                "value_indicators": {
                    "estimated_value": {
                        "amount": 15000
                    }
                },
                "vertical": "Home & Garden"
            }
        }
    ],
    "org_id": 1  # Change org_id to an integer
}

response = requests.post(url, headers=headers, json=body)
print(response.json())