from backend.app import app
from backend.config import FLASK_HOST, FLASK_PORT

if __name__ == "__main__":
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False)
