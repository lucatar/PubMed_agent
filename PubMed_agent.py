import requests
from openai import OpenAI
import json
import xml.etree.ElementTree as ET
import os
from dotenv import load_dotenv
import argparse

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def explore(obj, depth=0, max_depth=3):

    indent = "  " * depth

    if depth > max_depth:
        print(indent + "...")
        return

    # -------------------------
    # DICT (JSON object)
    # -------------------------
    if isinstance(obj, dict):
        print(f"{indent}{{dict}}")
        for k, v in obj.items():
            print(f"{indent}{k}:")
            explore(v, depth + 1, max_depth)

    # -------------------------
    # LIST
    # -------------------------
    elif isinstance(obj, list):
        print(f"{indent}[list len={len(obj)}]")
        for i, item in enumerate(obj[:3]):  # csak első 3 elem
            print(f"{indent}  [{i}]")
            explore(item, depth + 2, max_depth)

    # -------------------------
    # XML ELEMENT
    # -------------------------
    elif isinstance(obj, ET.Element):
        print(f"{indent}<{obj.tag}>")

        # attribútumok
        if obj.attrib:
            for k, v in obj.attrib.items():
                print(f"{indent}  @{k} = {v}")

        # text
        if obj.text and obj.text.strip():
            text = obj.text.strip()
            if len(text) > 100:
                text = text[:100] + "..."
            print(f"{indent}  TEXT: {text}")

        # children
        for child in obj:
            explore(child, depth + 1, max_depth)

    # -------------------------
    # STRING / INT / ETC
    # -------------------------
    else:
        text = str(obj)
        if len(text) > 120:
            text = text[:120] + "..."
        print(f"{indent}{text}")

def search_pubmed(query):
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"

    params = {
        "db": "pubmed",
        "term": query,
        "retmode": "json",
        "retmax": 20
    }

    response = requests.get(url, params=params)
    data = response.json()
    explore(data, depth=0, max_depth=5)  # 🔍 DEBUG (hasznos tanuláshoz, később ki lehet venni)
    # 🔍 DEBUG (hasznos tanuláshoz, később ki lehet venni)
    print("\n[DEBUG] ESEARCH RESPONSE:")
    print(json.dumps(data, indent=2))

    id_list = data.get("esearchresult", {}).get("idlist", [])

    if not id_list:
        return None

    return id_list


def fetch_pubmed_details(pmid):
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

    params = {
        "db": "pubmed",
        "id": pmid,
        "retmode": "xml"
    }

    response = requests.get(url, params=params)
    return response.text


def extract_abstracts(xml_text):
    root = ET.fromstring(xml_text)

    results = []

    for article in root.findall(".//PubmedArticle"):
        pmid = article.findtext(".//PMID")
        title = article.findtext(".//ArticleTitle")

        abstract_nodes = article.findall(".//AbstractText")

        abstract = " ".join(
            (a.text or "").strip()
            for a in abstract_nodes
            if a.text
        ).strip()

        results.append({
            "pmid": pmid,
            "title": title,
            "abstract": abstract if abstract else None
        })

    return results

def safe_text(node):
    return node.text.strip() if node is not None and node.text else None


def extract_pubmed_article(xml_text):
    root = ET.fromstring(xml_text)

    article = {}

    article["pmid"] = safe_text(root.find(".//MedlineCitation/PMID"))
    article["title"] = safe_text(root.find(".//ArticleTitle"))
    article["year"] = safe_text(root.find(".//ArticleDate"))
    article["journal"] = safe_text(root.find(".//Journal/Title"))
    article["authors"] = [safe_text(author) for author in root.findall(".//Author/LastName")]

    abstracts = root.findall(".//AbstractText")
    article["abstract"] = " ".join(
    "".join(a.itertext()).strip()
    for a in abstracts
    
    ) if abstracts else None

    return article

def summarize_text(text):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "You are a scientific assistant that summarizes biomedical abstracts clearly and concisely."
            },
            {
                "role": "user",
                "content": f"Summarize this abstract:\n\n{text}"
            }
        ]
    )

    return response.choices[0].message.content

def build_selection_prompt(report):

    prompt = f"""
You are a biomedical research assistant.

The user searched PubMed for:

"{report['query']}"

Below are the retrieved papers.

Your task is:

1. Select the 5 most relevant papers. Chose only from the paperts that have an abstract. If there are less than 5 papers with abstracts, select all of them. Prefer the newer papers.
2. Rank them from most relevant to least relevant.
3. For each paper briefly explain (1-2 sentences) why you selected it.

Return ONLY valid JSON in this format:

{{
    "selected_pmids": [
        {{
            "pmid": "...",
            "reason": "..."
        }}
    ]
}}

Retrieved papers:

"""

    for article in report["articles"]:

        prompt += f"""

PMID: {article['pmid']}
Title: {article['title']}
Journal: {article.get('journal')}
Year: {article.get('year')}
Abstract:
{article['abstract']}

"""

    return prompt

def build_summary_prompt(report, selected_pmids):

    selected_articles = [
        a for a in report["articles"]
        if a["pmid"] in selected_pmids
    ]

    prompt = f"""
You are a biomedical research assistant writing a mini literature review.

User query:
"{report['query']}"

Your task:
Write a structured scientific summary based ONLY on the selected papers.

The output must be in MARKDOWN format with these sections:

# 1. Overview of evidence
Summarize the main findings across all papers.

# 2. Key mechanisms / findings
Bullet points of main biological or clinical mechanisms.

# 3. Consensus in the literature
What do most studies agree on?

# 4. Limitations of current research
Methodological limitations, gaps, biases.

# 5. Research gaps and future directions
What is missing or unclear?

# 6. Conclusion
1 short paragraph.

IMPORTANT RULES:
- Only use the provided papers
- Do NOT add external knowledge
- Be scientific and cautious
- If evidence is weak, say so

---

SELECTED PAPERS:
"""

    for a in selected_articles:

        prompt += f"""

PMID: {a['pmid']}
Title: {a['title']}
Year: {a.get('year')}
Journal: {a.get('journal')}

Abstract:
{a['abstract']}

---
"""

    return prompt

# ---------------- MAIN ---------------- #

parser = argparse.ArgumentParser()
parser.add_argument("--query", required=True)
args = parser.parse_args()

query = args.query
#query = "CA1 pyramidal neurons dendritic spines"

pmids = search_pubmed(query)

structured_articles = []
raw_text_output = []
ai_summary = []

if not pmids:
    print("\n❌ Nincs találat a keresésre. Próbálj egyszerűbb kulcsszót.")
    exit()

print("\nTalált PMIDs:", pmids)


for pmid in pmids:
    xml_data = fetch_pubmed_details(pmid)
    print(xml_data[:1000])
    abstract = extract_abstracts(xml_data)
    article = extract_pubmed_article(xml_data)
    #summary = summarize_text(abstract)

    #print(article)

    structured_articles.append(article)
    #ai_summary.append(        
        #f"PMID: {article['pmid']}\n"
        #f"TITLE: {article['title']}\n"
        #f"SUMMARY: {summary}\n"
        #f"{'-'*50}\n"
    #)

    # RAW TEXT FILE CONTENT
    raw_text_output.append(
        f"PMID: {article['pmid']}\n"
        f"TITLE: {article['title']}\n"
        f"ABSTRACT: {article['abstract']}\n"
        f"{'-'*50}\n"
    )
    """
    if not abstract:
        print("\nPMID:", pmid)
        print("\n⚠️ Nincs abstract ebben a cikkben vagy nem sikerült kinyerni.")
    else:
        print("\n--- ABSTRACT ---\n")
        print("\nPMID:", pmid)
        print(abstract)
        #print("\n--- AI SUMMARY ---\n")
        #print(summary)
    """

# REPORT
report = {
    "query": query,
    "number_of_results": len(structured_articles),
    "articles": structured_articles
}

# ---------------------------
# 1. RAW TXT FILE
# ---------------------------
with open("raw_articles.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(raw_text_output))


# ---------------------------
# 2. STRUCTURED JSON FILE
# ---------------------------
with open("structured_articles.json", "w", encoding="utf-8") as f:
    json.dump(structured_articles, f, indent=2, ensure_ascii=False)

# ---------------------------
# 3. AI SUMMARY FILE
# ---------------------------
#with open("ai_summaries.txt", "w", encoding="utf-8") as f:
    #f.write("\n".join(ai_summary))

# ---------------------------
# 4. REPORT FILE
# ---------------------------
with open("report.json", "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2, ensure_ascii=False)

#Chose relevant articles and rank them, then explain why they were selected. Return only valid JSON in the specified format.

prompt = build_selection_prompt(report)

#Elmentjük külön a promptot, hogy később is vissza tudjuk nézni, mit küldtünk a GPT-nek.
with open("selection_prompt.txt", "w", encoding="utf-8") as f:
    f.write(prompt)

response = client.responses.create(
    model="gpt-4.1-mini",
    input=prompt
)

result_select = response.output_text

#print(result_select)

print("RAW RESULT:")
print(repr(result_select))
print("LENGTH:", len(result_select))

try:
    selected = json.loads(result_select)
except json.JSONDecodeError:
    print("❌ Invalid JSON from model:")
    print(result_select)
    raise


with open("selected_articles.json", "w", encoding="utf-8") as f:
    json.dump(selected, f, indent=2, ensure_ascii=False)

selected_pmids = [
    item["pmid"]
    for item in selected["selected_pmids"]
]


#Build a structured scientific summary based ONLY on the selected papers. The output must be in MARKDOWN format with specified sections.

summary_prompt = build_summary_prompt(report, selected_pmids)

response = client.responses.create(
    model="gpt-4.1-mini",
    input=summary_prompt
)

final_summary = response.output_text

with open("final_summary.txt", "w", encoding="utf-8") as f:
    f.write(final_summary)

print("\nKész:")
print("- raw_articles.txt")
print("- structured_articles.json")
#print("- ai_summaries.txt")
print("- report.json")
print("- selected_articles.json")
print("- final_summary.txt")
