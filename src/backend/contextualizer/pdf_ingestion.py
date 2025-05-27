import os
from PyPDF2 import PdfReader

DATA_DIR = ".data"
OUTPUT_DIR = ".data/markdown"

os.makedirs(OUTPUT_DIR, exist_ok=True)

def pdf_to_markdown(pdf_path, md_path):
    reader = PdfReader(pdf_path)
    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text
            text += "\n\n"
    # Simple markdown formatting: wrap text in paragraphs
    md_content = "\n\n".join([para.strip() for para in text.split('\n\n') if para.strip()])
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

def main():
    for filename in os.listdir(DATA_DIR):
        if filename.lower().endswith(".pdf"):
            pdf_path = os.path.join(DATA_DIR, filename)
            md_filename = os.path.splitext(filename)[0] + ".md"
            md_path = os.path.join(OUTPUT_DIR, md_filename)
            pdf_to_markdown(pdf_path, md_path)
            print(f"Converted {filename} to {md_filename}")

if __name__ == "__main__":
    main()
