#!/usr/bin/env python3
"""
Anki Flashcard Exporter
Parses Socratic Check Questions & Answers and Wrong Mental Models across all curriculum files and exports an importable CSV file.
"""

import glob
import os
import csv
import re

def export_anki_cards(output_csv):
    all_files = glob.glob(r'c:\Users\dpacg\System-design\**\*.md', recursive=True)
    cards = []

    for fpath in all_files:
        if 'node_modules' in fpath or '.git' in fpath or 'scratch' in fpath or 'answers' in fpath:
            continue
            
        rel_path = os.path.basename(fpath)
        with open(fpath, 'r', encoding='utf-8') as fp:
            content = fp.read()

        # 1. Parse Wrong Mental Models
        if "## Wrong Mental Models" in content or "### Wrong Mental Models" in content:
            matches = re.findall(r'(\d+\.\s+\*\*Mental Model:\*\*\s+.*?)(?=\n\d+\.|\n#|\Z)', content, re.DOTALL)
            for match in matches:
                lines = match.strip().splitlines()
                front = f"[{rel_path}] {lines[0]}"
                back = "\n".join(lines[1:]).strip()
                cards.append((front, back, "MentalModel"))

        # 2. Parse Socratic Checks
        if "🛑 SOCRATIC CHECK" in content:
            q_matches = re.findall(r'\*\*Question\s+\d+:\*\*\s*(.*?)(?=\n\*\*Question|\n>|\n#|\Z)', content, re.DOTALL)
            for q in q_matches:
                front = f"[{rel_path}] Socratic Question: {q.strip()}"
                back = f"See complete Socratic Answer Key in answers/{rel_path}"
                cards.append((front, back, "SocraticCheck"))

    with open(output_csv, 'w', encoding='utf-8', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["Front", "Back", "Tags"])
        for front, back, tag in cards:
            writer.writerow([front, back, tag])

    print(f"Successfully exported {len(cards)} Anki flashcards to {output_csv}")

if __name__ == "__main__":
    export_anki_cards(r"c:\Users\dpacg\System-design\tools\system_design_anki_cards.csv")
