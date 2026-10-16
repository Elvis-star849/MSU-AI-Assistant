import os

# The app's question log (logs/questions.jsonl) is for real use; UI tests must not write to it.
os.environ.setdefault("MSU_QUESTION_LOG", "off")
