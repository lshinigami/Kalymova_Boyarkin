from flask import Flask, render_template, request, redirect
import secrets
import re
app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

@app.route('/')
def index():
    return render_template('home.html')

if __name__ == '__main__':
    app.run(debug=True)
