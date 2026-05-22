import requests

def check_t1_8():
    try:
        url = "http://localhost:8000/api/leads/score/bulk/async"  # Zmeniť na aktuálny port, ak je potrebné
        payload = {
            "leads": [{"lead_data": {"key": "value1"}, "org_config": {"org_key": "org_value1"}}],
            "org_id": "test_org_id"
        }
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            print("T1.8 OK: Response received successfully.")
            print("Response data:", response.json())
        else:
            print("T1.8 failed with status code:", response.status_code)
            print("Response text:", response.text)
    except Exception as e:
        print("Error during request:", str(e))

if __name__ == "__main__":
    check_t1_8()