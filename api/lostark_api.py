import urllib.parse
import requests
import os

HEADERS = {
    "accept": "application/json",
    "authorization": f"bearer {os.getenv("API_KEY")}"
}

def get_expedition(character_name: str):
    encoded_name = urllib.parse.quote(character_name)
    url = f"{os.getenv("BASE_URL")}/characters/{encoded_name}/siblings"
    
    response = requests.get(url, headers=HEADERS)
    
    if response.status_code == 200:
        raw_data = response.json()

        return raw_data 
    return None