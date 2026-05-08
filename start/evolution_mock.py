from __future__ import annotations

from flask import Flask, jsonify, request

app = Flask(__name__)


def _mask_number(number: str) -> str:
    text = str(number or "")
    if len(text) <= 4:
        return text
    return f"***{text[-4:]}"


@app.get("/")
def root():
    return jsonify({"status": "running", "service": "evolution-mock"}), 200


@app.post("/message/sendText/<instance>")
def send_text(instance: str):
    payload = request.get_json(silent=True) or {}
    number = payload.get("number", "")
    text = payload.get("text", "")
    return (
        jsonify(
            {
                "status": "PENDING",
                "instance": instance,
                "number": _mask_number(str(number)),
                "message_preview": str(text)[:80],
            }
        ),
        201,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
