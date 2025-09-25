import os
import re
import secrets
import sqlite3

from argon2 import PasswordHasher
from argon2.exceptions import *
from flask import Flask, render_template, request, redirect

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
ph = PasswordHasher()

with sqlite3.connect('my_database.db') as conn:
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users(
                       id INTEGER PRIMARY KEY,
                       login VARCHAR(50) UNIQUE COLLATE NOCASE NOT NULL,
                       email VARCHAR(89) UNIQUE COLLATE NOCASE NOT NULL,
                       password VARCHAR(36))
                   ''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS groups(
                       id INTEGER PRIMARY KEY,
                       group_name VARCHAR(50) UNIQUE COLLATE NOCASE NOT NULL)
                    ''')
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS subscriptions(
                       user_id INTEGER,
                       group_id INTEGER,
                       FOREIGN KEY (user_id) REFERENCES users(id),
                       FOREIGN KEY(group_id) REFERENCES groups(id),
                       PRIMARY KEY(user_id,group_id))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS posts(
                       id INTEGER PRIMARY KEY,
                       uploader_group_id INTEGER NOT NULL,
                       uploader_user_id INTEGER NOT NULL,
                       upload_date VARCHAR(50) NOT NULL,
                       title VARCHAR(50) NOT NULL,
                       desc VARCHAR(250),
                       attach_img VARCHAR(250),
                       rating INTEGER,
                       FOREIGN KEY(uploader_group_id) REFERENCES groups(id),
                       FOREIGN KEY(uploader_user_id) REFERENCES users(id))''')
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS likes_dislikes_posts(
                       user_id INTEGER,
                       post_id INTEGER,
                       likeorno BOOLEAN NOT NULL,
                       FOREIGN KEY(user_id) REFERENCES users(id),
                       FOREIGN KEY(post_id) REFERENCES posts(id),
                       PRIMARY KEY(user_id,post_id))''')
    cursor.execute('''INSERT OR IGNORE INTO users (login, email, password) VALUES (?, ?, ?)''', ('Anonymous','',''))

def is_safe_folder(folder_name, base_dir):
    folder_name = folder_name.lower()
    if re.match(r'^[a-zA-Z0-9_-]+$', folder_name) is None:
        return False
    base_dir = 'static/' + base_dir
    if os.path.sep in folder_name or (os.path.altsep and os.path.altsep in folder_name):
        return False
    full_path = os.path.abspath(os.path.join(base_dir, folder_name))
    base_dir = os.path.abspath(base_dir)
    if not full_path.startswith(base_dir + os.path.sep):
        return False
    return os.path.isdir(full_path)

@app.route('/u/<login>', methods=['GET','POST'])
def profile(login):
    if not is_safe_folder(login, 'u'):
        #Return an error page 404
        pass
    if request.method == 'GET':
        return render_template('profile.html', clogin="Manul", login=login)
    elif request.method == 'POST':
        if 'email' in request.form:
            #Change email or pass or both
            pass
        elif 'avatar' in request.files:
            #Change avatar
            pass
        elif 'logout' in request.form:
            #Logout user
            pass
        else:
            return redirect(f'/u/{login}')

@app.route('/', methods=['GET'])
def index():
    #q = request.args.get('q', '').lower()
    filter = request.args.get('filter', '').lower()
    return render_template('home.html', filter=filter)

if __name__ == '__main__':
    app.run()