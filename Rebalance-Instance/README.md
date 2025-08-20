cp .env.example .env
# edit .env isi kredensial & parameter
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
