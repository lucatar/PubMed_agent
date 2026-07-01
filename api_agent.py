import requests
import json

def get_post(post_id):
    url = f"https://jsonplaceholder.typicode.com/posts/{post_id}"
    response = requests.get(url)
    return response.json()


def analyze_post(post):
    return {
        "title": post["title"],
        "word_count": len(post["body"].split()),
        "is_long": len(post["body"].split()) > 20
    }


post = get_post(1)
result = analyze_post(post)

print(json.dumps(result, indent=2, ensure_ascii=False))