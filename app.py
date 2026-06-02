from dotenv import load_dotenv

load_dotenv()

from flask import Flask
from routes import bp
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False  # ← agregá esto
app.register_blueprint(bp)

if __name__ == "__main__":
    app.run(debug=True, port=9200)