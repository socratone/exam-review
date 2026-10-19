"""로컬 .env의 LangSmith 설정을 Modal Secret에 저장한다. 키는 출력하지 않는다."""
import os

import modal
from dotenv import load_dotenv


def main():
    load_dotenv(".env", override=False)
    if not os.getenv("LANGSMITH_API_KEY"):
        raise SystemExit("Set LANGSMITH_API_KEY in .env first.")
    name = os.getenv("EXAM_CHECKER_LANGSMITH_SECRET") or "exam-checker-langsmith"
    settings = {
        "LANGSMITH_API_KEY": os.environ["LANGSMITH_API_KEY"],
        "LANGSMITH_TRACING": os.getenv("LANGSMITH_TRACING", "false"),
        "LANGSMITH_PROJECT": os.getenv("LANGSMITH_PROJECT", "exam-checker"),
        "LANGSMITH_ENDPOINT": os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"),
        "EXAM_CHECKER_TRACE_CONTENT": os.getenv("EXAM_CHECKER_TRACE_CONTENT", "false"),
    }
    modal.Secret.objects.create(name, settings, allow_existing=True)
    modal.Secret.from_name(name).update(settings)
    print(f"Modal Secret saved: {name}. Set EXAM_CHECKER_LANGSMITH_SECRET={name} and redeploy.")


if __name__ == "__main__":
    main()
