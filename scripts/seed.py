import json
import sys
from pathlib import Path

import requests


def main() -> None:
    api_base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    data_path = Path(__file__).resolve().parents[1] / "sample_data" / "applications.json"
    income_cert = Path(__file__).resolve().parents[1] / "sample_data" / "income_certificate.txt"
    caste_cert = Path(__file__).resolve().parents[1] / "sample_data" / "caste_certificate.txt"
    payload = json.loads(data_path.read_text())

    for item in payload:
        form = {
            "applicant_id": item["applicant_id"],
            "name": item["name"],
            "income": str(item["income"]),
            "cgpa": str(item["cgpa"]),
            "category": item["category"],
        }
        files = {
            "income_certificate": income_cert.open("rb"),
        }
        if item["category"].lower() != "general":
            files["caste_certificate"] = caste_cert.open("rb")

        response = requests.post(
            f"{api_base}/applications",
            data=form,
            files=files,
            timeout=10,
        )
        for fp in files.values():
            fp.close()
        if response.status_code == 409:
            print(f"Duplicate: {item['applicant_id']}")
        else:
            print(response.status_code, response.json())


if __name__ == "__main__":
    main()
