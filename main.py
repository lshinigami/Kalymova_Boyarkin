import os
import re
import secrets
import shutil
import sqlite3
from datetime import datetime

from PIL import Image
from argon2 import PasswordHasher
from argon2.exceptions import *
from flask import Flask, render_template, request, redirect, send_from_directory
from flask_login import LoginManager, UserMixin, login_user, current_user, logout_user
from flask_socketio import SocketIO
from werkzeug.utils import secure_filename

app = Flask(__name__)
# app.config['REMEMBER_COOKIE_DURATION']=timedelta(days=10)
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
app.secret_key = secrets.token_hex(32)
UPLOAD_FOLDER = os.path.join(app.root_path, 'uploads')
socketio = SocketIO(app)

login_manager = LoginManager()
login_manager.init_app(app)
ph = PasswordHasher()

necessary_folders=['uploads','uploads/g','uploads/p','uploads/u','database']
for nfolder in necessary_folders:
    os.makedirs(nfolder, exist_ok=True)

with sqlite3.connect('database/db.db') as conn:
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users(
                       id INTEGER PRIMARY KEY,
                       login VARCHAR(30) UNIQUE COLLATE NOCASE NOT NULL,
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
                       role VARCHAR(5) COLLATE NOCASE NOT NULL,
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
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS comments(
                       id INTEGER PRIMARY KEY,
                       desc VARCHAR(250),
                       upload_date VARCHAR(50) NOT NULL,
                       user_id INTEGER,
                       post_id INTEGER,
                       rating INTEGER,
                       FOREIGN KEY(user_id) REFERENCES users(id),
                       FOREIGN KEY(post_id) REFERENCES posts(id))''')
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS likes_dislikes_comments(
                       user_id INTEGER,
                       comment_id INTEGER,
                       likeorno BOOLEAN NOT NULL,
                       FOREIGN KEY(user_id) REFERENCES users(id),
                       FOREIGN KEY(comment_id) REFERENCES comments(id),
                       PRIMARY KEY(user_id,comment_id))''')
    cursor.execute('''INSERT OR IGNORE INTO users (login, email, password) VALUES (?, ?, ?)''', ('Anonymous','',''))


def is_safe_folder(folder_name, base_dir, whatdo="exist"):
    folder_name = folder_name.lower()
    if re.match(r'^[a-zA-Z0-9_-]+$', folder_name) is None:
        return False
    base_dir = 'uploads/' + base_dir
    if os.path.sep in folder_name or (os.path.altsep and os.path.altsep in folder_name):
        return False
    full_path = os.path.abspath(os.path.join(base_dir, folder_name))
    base_dir = os.path.abspath(base_dir)
    if not full_path.startswith(base_dir + os.path.sep):
        return False
    if whatdo == "exist":
        return os.path.isdir(full_path)
    elif whatdo == "create":
        if os.path.isdir(full_path):
            return False
        os.makedirs(full_path, exist_ok=True)
        return full_path
    elif whatdo == "delete":
        if not os.path.isdir(full_path):
            return False
        shutil.rmtree(full_path)
        return full_path
    elif whatdo == "safe":
        return True
    return None

def img_process(image, what="ava"):
    #Also it would probably be a good idea to implement some kind of "virus check" for safety
    image = Image.open(image)
    image = image.convert('RGB')
    width, height = image.size
    new_size = (768 if what == "banner" else 500, 500)
    if what == "banner":
        if round((768 * height) / width) < 500:
            new_size = (round((500 * width) / height), 500)
        elif round((768 * height) / width) > 500:
            new_size = (768, round((768 * height) / width))
    else:
        if width < height:
            new_size = (500, round((500 * height) / width))
        elif width > height:
            new_size = (round((500 * width) / height), 500)
    image = image.resize(new_size, Image.Resampling.LANCZOS)
    width, height = image.size

    if what == "banner":
        left = (width - 768) / 2
        right = (width + 768) / 2
    else:
        left = (width - 500) / 2
        right = (width + 500) / 2
    top = (height - 500) / 2
    bottom = (height + 500) / 2
    image = image.crop((left, top, right, bottom))
    return image

def rating_count(post):
    rating_post = post['rating'] if type(post) == dict else post
    new_format = rating_post
    if 1_000 <= abs(rating_post) < 1_000_000:
        new_format = str(round(rating_post / 1_000, 1)) + 'k'
    elif 1_000_000 <= abs(rating_post) < 1_000_000_000:
        new_format = str(round(rating_post / 1_000_000, 1)) + 'm'
    elif 1_000_000_000 <= abs(rating_post):
        new_format = str(round(rating_post / 1_000_000_000, 1)) + 'b'
    if type(post) == dict:
        post['rating'] = new_format
        return post
    else:
        return new_format


class User(UserMixin):
    def __init__(self, id_, login, email, password_hash):
        self.id = id_
        self.login = login
        self.email = email
        self.password_hash = password_hash

    @staticmethod
    def get(user_id):
        with sqlite3.connect('database/db.db') as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            if row:
                return User(*row)
            return None

    @staticmethod
    def find_by_login(login):
        with sqlite3.connect('database/db.db') as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE login = ?", (login,))
            row = cursor.fetchone()
            if row:
                return User(*row)
            return None

    @staticmethod
    def find_by_email(email):
        with sqlite3.connect('database/db.db') as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
            row = cursor.fetchone()
            if row:
                return User(*row)
            return None

    def check_password(self, password):
        try:
            ph.verify(self.password_hash, password)
            return True
        except (InvalidHashError, VerifyMismatchError, VerificationError) as _:
            return False

    @classmethod
    def create(cls, login, email, password_hash):
        with sqlite3.connect('database/db.db') as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("INSERT INTO users (login, email, password) VALUES (?, ?, ?)",
                               (login, email, password_hash))
            except sqlite3.IntegrityError:
                return None
            conn.commit()
        return cls.find_by_login(login)


@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)

@socketio.on('change_rating_com')
def change_rating(data):
    if current_user.is_authenticated and current_user.id!=1:
        commentId = data.get('commentId', 0)
        if commentId and commentId.isnumeric():
            commentId = int(commentId)
        else:
            commentId = 0
        what = data.get('what', 0)
        clickedElementId = data.get('clickedElementId', None)
        commentrating = None
        if commentId and what and clickedElementId:
            with sqlite3.connect('database/db.db') as conn:
                cursor = conn.cursor()
                cursor.execute('''SELECT comments.id, desc, upload_date, u.login, post_id, rating, (SELECT GROUP_CONCAT(login)
                                  FROM (SELECT u2.login
                                  FROM likes_dislikes_comments
                                  INNER JOIN users u2 on likes_dislikes_comments.user_id = u2.id
                                  WHERE comment_id = comments.id AND likeorno = TRUE
                                  ORDER BY user_id)) as likes, (SELECT GROUP_CONCAT(login)
                                  FROM (SELECT u2.login
                                  FROM likes_dislikes_comments
                                  INNER JOIN users u2 on likes_dislikes_comments.user_id = u2.id
                                  WHERE comment_id = comments.id AND likeorno = FALSE
                                  ORDER BY user_id)) AS dislikes
                          FROM comments INNER JOIN users u
                          ON comments.user_id = u.id
                          WHERE comments.id = ?''', (commentId,))
                row = cursor.fetchone()
                if row:
                    should_we_continue=True #To prevent exploit
                    with sqlite3.connect('database/db.db') as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            '''SELECT likeorno FROM likes_dislikes_comments WHERE user_id = ? AND comment_id = ?''',
                            (current_user.id, commentId))
                        row1 = cursor.fetchone()
                        if row1:
                            likeorno = row1[0]
                            if likeorno:
                                if clickedElementId == "like-button" and what!=-1:
                                    should_we_continue=False
                                elif clickedElementId == "dislike-button" and what!=-2:
                                    should_we_continue=False
                            else:
                                if clickedElementId == "like-button" and what!=2:
                                    should_we_continue=False
                                elif clickedElementId == "dislike-button" and what!=1:
                                    should_we_continue=False
                        else:
                            if what<=-2 or what>=2:
                                should_we_continue=False
                            elif clickedElementId == "like-button" and what==-1:
                                should_we_continue=False
                            elif clickedElementId == "dislike-button" and what==1:
                                should_we_continue=False
                    if should_we_continue:
                        temp_comment_rating = row[5]
                        temp_comment_rating += what
                        with sqlite3.connect('database/db.db') as conn:
                            cursor = conn.cursor()
                            cursor.execute('''UPDATE comments
                                              SET rating = ?
                                              WHERE id = ?;''', (temp_comment_rating, commentId))
                            conn.commit()
                        if clickedElementId == "like-button":
                            if what >= 1:
                                with sqlite3.connect('database/db.db') as conn:
                                    cursor = conn.cursor()
                                    cursor.execute(
                                        '''INSERT OR REPLACE into likes_dislikes_comments(user_id, comment_id, likeorno) VALUES (?, ?, ?)''',
                                        (current_user.id, commentId, True))
                                    conn.commit()
                            else:
                                with sqlite3.connect('database/db.db') as conn:
                                    cursor = conn.cursor()
                                    cursor.execute('''DELETE
                                                      FROM likes_dislikes_comments
                                                      WHERE comment_id = ?
                                                        and user_id = ?;''', (commentId, current_user.id))
                                    conn.commit()
                        elif clickedElementId == "dislike-button":
                            if what <= -1:
                                with sqlite3.connect('database/db.db') as conn:
                                    cursor = conn.cursor()
                                    cursor.execute(
                                        '''INSERT OR REPLACE into likes_dislikes_comments(user_id, comment_id, likeorno) VALUES (?, ?, ?)''',
                                        (current_user.id, commentId, False))
                                    conn.commit()
                            else:
                                with sqlite3.connect('database/db.db') as conn:
                                    cursor = conn.cursor()
                                    cursor.execute('''DELETE
                                                      FROM likes_dislikes_comments
                                                      WHERE comment_id = ?
                                                        and user_id = ?;''', (commentId, current_user.id))
                                    conn.commit()
                        commentrating = rating_count(temp_comment_rating)
        if commentrating is not None:
            socketio.emit(f'scs_change_rating_com_{current_user.login}',
                          {"commentId": commentId, "new_rating": commentrating, "what": what, "clickedElementId": clickedElementId})
    else:
        None

@socketio.on('change_rating')
def change_rating(data):
    if current_user.is_authenticated and current_user.id!=1:
        postId = data.get('postId', 0)
        if postId and postId.isnumeric():
            postId = int(postId)
        else:
            postId = 0
        what = data.get('what', 0)
        clickedElementId = data.get('clickedElementId', None)
        postrating = None
        if postId and what and clickedElementId:
            with sqlite3.connect('database/db.db') as conn:
                cursor = conn.cursor()
                cursor.execute('''SELECT posts.id,
                                         group_name,
                                         u.login,
                                         upload_date,
                                         title, desc, attach_img, rating, (SELECT GROUP_CONCAT(login)
                                      FROM (SELECT u2.login
                                      FROM likes_dislikes_posts
                                      INNER JOIN main.users u2 on likes_dislikes_posts.user_id = u2.id
                                      WHERE post_id = posts.id AND likeorno = TRUE
                                      ORDER BY user_id)) as likes, (SELECT GROUP_CONCAT(login)
                                      FROM (SELECT u2.login
                                      FROM likes_dislikes_posts
                                      INNER JOIN main.users u2 on likes_dislikes_posts.user_id = u2.id
                                      WHERE post_id = posts.id AND likeorno = FALSE
                                      ORDER BY user_id)) AS dislikes
                                  FROM posts INNER JOIN main.groups g
                                  on posts.uploader_group_id = g.id INNER JOIN main.users u on u.id = posts.uploader_user_id
                                  WHERE posts.id = ?''', (postId,))
                row = cursor.fetchone()
                if row:
                    should_we_continue=True #To prevent exploit
                    with sqlite3.connect('database/db.db') as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            '''SELECT likeorno FROM likes_dislikes_posts WHERE user_id = ? AND post_id = ?''',
                            (current_user.id, postId))
                        row1 = cursor.fetchone()
                        if row1:
                            likeorno = row1[0]
                            if likeorno:
                                if clickedElementId == "like-button" and what!=-1:
                                    should_we_continue=False
                                elif clickedElementId == "dislike-button" and what!=-2:
                                    should_we_continue=False
                            else:
                                if clickedElementId == "like-button" and what!=2:
                                    should_we_continue=False
                                elif clickedElementId == "dislike-button" and what!=1:
                                    should_we_continue=False
                        else:
                            if what<=-2 or what>=2:
                                should_we_continue=False
                            elif clickedElementId == "like-button" and what==-1:
                                should_we_continue=False
                            elif clickedElementId == "dislike-button" and what==1:
                                should_we_continue=False
                    if should_we_continue:
                        temp_post_rating = row[7]
                        temp_post_rating += what
                        with sqlite3.connect('database/db.db') as conn:
                            cursor = conn.cursor()
                            cursor.execute('''UPDATE posts
                                              SET rating = ?
                                              WHERE id = ?;''', (temp_post_rating, postId))
                            conn.commit()
                        if clickedElementId == "like-button":
                            if what >= 1:
                                with sqlite3.connect('database/db.db') as conn:
                                    cursor = conn.cursor()
                                    cursor.execute(
                                        '''INSERT OR REPLACE into likes_dislikes_posts(user_id, post_id, likeorno) VALUES (?, ?, ?)''',
                                        (current_user.id, postId, True))
                                    conn.commit()
                            else:
                                with sqlite3.connect('database/db.db') as conn:
                                    cursor = conn.cursor()
                                    cursor.execute('''DELETE
                                                      FROM likes_dislikes_posts
                                                      WHERE post_id = ?
                                                        and user_id = ?;''', (postId, current_user.id))
                                    conn.commit()
                        elif clickedElementId == "dislike-button":
                            if what <= -1:
                                with sqlite3.connect('database/db.db') as conn:
                                    cursor = conn.cursor()
                                    cursor.execute(
                                        '''INSERT OR REPLACE into likes_dislikes_posts(user_id, post_id, likeorno) VALUES (?, ?, ?)''',
                                        (current_user.id, postId, False))
                                    conn.commit()
                            else:
                                with sqlite3.connect('database/db.db') as conn:
                                    cursor = conn.cursor()
                                    cursor.execute('''DELETE
                                                      FROM likes_dislikes_posts
                                                      WHERE post_id = ?
                                                        and user_id = ?;''', (postId, current_user.id))
                                    conn.commit()
                        postrating = rating_count(temp_post_rating)
        if postrating is not None:
            socketio.emit(f'scs_change_rating_{current_user.login}',
                          {"postId": postId, "new_rating": postrating, "what": what, "clickedElementId": clickedElementId})
    else:
        None

@app.route('/p/',methods=['GET'])
def empty_post():
    return redirect('/?filter=popular')

@app.route('/u/',methods=['GET','POST'])
def auth():
    what = request.args.get('w', 'signin').lower()
    what = 'signin' if what not in ['signin','signup'] else what
    if request.method == 'GET':
        return render_template('auth.html', what=what)
    elif request.method == 'POST':
        login = re.sub(r"\s+", '_', request.form.get('login', ''))
        email = request.form.get('email', '')
        password = request.form.get('password', '')
        if 0<len(login)<=30 and 0<len(password)<=36 and login.lower()!='anonymous' and (len(password)>=8 and re.search(r"^[A-Za-z0-9!@#$%^&*()-_=+\[\]{}|;:'\",.<>/?~]+$",password)):
            if what=='signup' and 0<len(email)<=89 and re.match(r'^[a-zA-Z0-9_-]+$',login) is not None and re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email) is not None:
                if is_safe_folder(login, 'u', 'create'):
                    user = User.create(login, email, ph.hash(password))
                    if user:
                        login_user(user)
                        return redirect(f'/u/{user.login}')
                    else:
                        return "Error :)\nThis user is already registered."
                return "Error :)\nField is incorrectly formated. Unsafe username."
            elif what=='signin':
                if re.match(r'^[a-zA-Z0-9_-]+$', login) is not None:
                    user = User.find_by_login(login)
                elif re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', login) is not None:
                    user = User.find_by_email(login)
                else:
                    return "Error :)\nField is incorrectly formated. (JS should have detected that)"
                if user:
                    if user.check_password(password):
                        login_user(user)
                        return redirect(f'/u/{user.login}')
                    else:
                        return "Error :)\nPassword is incorrect"
                else:
                    return "Error :)\nUser not found"
            else:
                return "Error :)\nField is incorrectly formated. (JS should have detected that)"
        else:
            return "Error :)\nField is incorrectly formated. (JS should have detected that)"


@app.route('/g/',methods=['GET','POST'])
def new_group():
    if current_user.is_anonymous:
        login_user(load_user(1))
        return redirect('/u/')
    if current_user.id==1:
        return redirect('/u/')
    if request.method == 'GET':
        return render_template('new_group.html')
    elif request.method == 'POST':
        group_name = request.form.get('group_name','')
        gava = request.files['gava']
        gban = request.files['gban']
        if group_name and re.match(r'^[a-zA-Z0-9_-]+$', group_name) is not None:
            if is_safe_folder(group_name, 'g', 'create'):
                with sqlite3.connect('database/db.db') as conn:
                    cursor = conn.cursor()
                    try:
                        cursor.execute("INSERT INTO groups (group_name) VALUES (?)",
                                       (group_name,))
                    except sqlite3.IntegrityError:
                        return "Error :)\nThis user is already registered."
                    conn.commit()
                with sqlite3.connect('database/db.db') as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT id FROM groups WHERE group_name = ?", (group_name,))
                    row = cursor.fetchone()
                    group_id = row[0]
                with sqlite3.connect('database/db.db') as conn:
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO subscriptions (user_id,group_id,role) VALUES (?,?,'creat')",
                                       (current_user.id,group_id))
                    conn.commit()
                if gava.filename != '':
                    image = img_process(gava.stream, what="ava")
                    filename = os.path.join(f'uploads/g', group_name.lower(), 'ava.jpg')
                    image.save(filename)
                if gban.filename != '':
                    image = img_process(gban.stream, what="banner")
                    filename = os.path.join(f'uploads/g', group_name.lower(), 'banner.jpg')
                    image.save(filename)
                return redirect(f'/g/{group_name}')
            else:
                return "Error :)\nField is incorrectly formated. Unsafe group name."
        else:
            return "Error :)\nField is incorrectly formated. (JS should have detected that)"

@app.route('/p/<post>',methods=['GET','POST'])
def posts(post):
    if current_user.is_anonymous:
        login_user(load_user(1))
    page = request.args.get('p', '1')
    if not page.isnumeric():
        page = '1'
    page = abs(int(page))
    if page <= 0:
        page = 1
    subs = {}
    with sqlite3.connect('database/db.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''SELECT GROUP_CONCAT(group_name)
                          FROM (SELECT group_name
                                FROM subscriptions
                                         INNER JOIN groups ON subscriptions.group_id = groups.id
                                WHERE user_id = ?
                                ORDER BY group_id)''', (current_user.id,))
        row = cursor.fetchone()
        if row[0]:
            subs = sorted({sub for sub in row[0].split(',') if is_safe_folder(sub, 'g', 'exist')})
    with sqlite3.connect('database/db.db') as conn:
        cursor = conn.cursor()
        cursor.execute("""SELECT groups.group_name,
                                 GROUP_CONCAT(login) AS user_ids
                          FROM groups
                                   LEFT JOIN subscriptions
                                             ON subscriptions.group_id = groups.id
                                                 AND subscriptions.role IN ('creat', 'moder')
                                   INNER JOIN users on subscriptions.user_id = users.id
                          GROUP BY groups.group_name
                          ORDER BY groups.group_name;""")
        mods_in_groups = dict(cursor.fetchall())
    if is_safe_folder(post, 'p', "exist"):
        with sqlite3.connect('database/db.db') as conn:
            cursor = conn.cursor()
            cursor.execute('''SELECT posts.id,
                                     group_name,
                                     u.login,
                                     upload_date,
                                     title, desc, attach_img, rating, (SELECT GROUP_CONCAT(login)
                                  FROM (SELECT u2.login
                                  FROM likes_dislikes_posts
                                  INNER JOIN main.users u2 on likes_dislikes_posts.user_id = u2.id
                                  WHERE post_id = posts.id AND likeorno = TRUE
                                  ORDER BY user_id)) as likes, (SELECT GROUP_CONCAT(login)
                                  FROM (SELECT u2.login
                                  FROM likes_dislikes_posts
                                  INNER JOIN main.users u2 on likes_dislikes_posts.user_id = u2.id
                                  WHERE post_id = posts.id AND likeorno = FALSE
                                  ORDER BY user_id)) AS dislikes, uploader_group_id
                              FROM posts INNER JOIN main.groups g
                              on posts.uploader_group_id = g.id INNER JOIN main.users u on u.id = posts.uploader_user_id
                              WHERE posts.id = ?''', (post,))
            row = cursor.fetchone()
            who_rem_in_this_post = mods_in_groups.get(row[1], '').lower().split(',')
            singular_post=rating_count({'id': row[0], 'g': row[1], 'g_id': row[10], 'u': row[2], 'upload_date': '.'.join(row[3].split('.')[::-1]), 'title': row[4],
                               'desc': row[5],
                               'attach_img': row[6], 'rating': row[7],
                               'liked_by': set(row[8].lower().split(',') if row[8] else []),
                               'disliked_by': set(row[9].lower().split(',') if row[9] else []),
                               'who_rem': set(who_rem_in_this_post + [row[2].lower()])})
    else:
        return render_template('error.html', login=current_user.login, subs=subs)
    #Select comments
    with sqlite3.connect('database/db.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''SELECT comments.id, desc, upload_date, u.login, post_id, rating, (SELECT GROUP_CONCAT(login)
                                  FROM (SELECT u2.login
                                  FROM likes_dislikes_comments
                                  INNER JOIN users u2 on likes_dislikes_comments.user_id = u2.id
                                  WHERE comment_id = comments.id AND likeorno = TRUE
                                  ORDER BY user_id)) as likes, (SELECT GROUP_CONCAT(login)
                                  FROM (SELECT u2.login
                                  FROM likes_dislikes_comments
                                  INNER JOIN users u2 on likes_dislikes_comments.user_id = u2.id
                                  WHERE comment_id = comments.id AND likeorno = FALSE
                                  ORDER BY user_id)) AS dislikes,
                                  (rating * 1.0) / (julianday('now') -julianday('20' || REPLACE(upload_date,'.','-'))+1) AS popularity_score
                          FROM comments INNER JOIN users u
                          ON comments.user_id = u.id
                          WHERE comments.post_id = ? ORDER BY popularity_score DESC''', (post,))
        how_many_are_there_posts = len(cursor.fetchall())
        cursor.execute('''SELECT comments.id, desc, upload_date, u.login, post_id, rating, (SELECT GROUP_CONCAT(login)
                                  FROM (SELECT u2.login
                                  FROM likes_dislikes_comments
                                  INNER JOIN users u2 on likes_dislikes_comments.user_id = u2.id
                                  WHERE comment_id = comments.id AND likeorno = TRUE
                                  ORDER BY user_id)) as likes, (SELECT GROUP_CONCAT(login)
                                  FROM (SELECT u2.login
                                  FROM likes_dislikes_comments
                                  INNER JOIN users u2 on likes_dislikes_comments.user_id = u2.id
                                  WHERE comment_id = comments.id AND likeorno = FALSE
                                  ORDER BY user_id)) AS dislikes,
                                  (rating * 1.0) / (julianday('now') -julianday('20' || REPLACE(upload_date,'.','-'))+1) AS popularity_score
                          FROM comments INNER JOIN users u
                          ON comments.user_id = u.id
                          WHERE comments.post_id = ? ORDER BY popularity_score DESC LIMIT 5 OFFSET ?''', (post,5*(page-1)))
        rows = cursor.fetchall()
        temp_comments = {row[0]:
                             {'id': row[0], 'desc': row[1], 'upload_date': '.'.join(row[2].split('.')[::-1]), 'u': row[3],
                              'rating': row[5], 'liked_by': set(row[6].lower().split(',') if row[6] else []),
                 'disliked_by': set(row[7].lower().split(',') if row[7] else []), 'who_rem': set(who_rem_in_this_post + [row[3].lower()])} for
                         row in rows}
        comments = {id: rating_count(comment.copy()) for id, comment in temp_comments.items()}
    #Select current user's role in current group
    current_role = 'unknown'
    with sqlite3.connect('database/db.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''SELECT role
                          FROM subscriptions
                          WHERE user_id = ?
                            AND group_id = ?''', (current_user.id, singular_post['g_id']))
        row = cursor.fetchone()
        if row:
            current_role = row[0]
    if request.method == 'GET':
        return render_template('posts.html', login=current_user.login, subs=subs, post=singular_post, comments=comments.values(), page=page, total_pages=how_many_are_there_posts)
    elif request.method == 'POST':
        if current_user.is_anonymous:
            login_user(load_user(1))
            return redirect('/u/')
        if current_user.id == 1:
            return redirect('/u/')
        if 'comment' in request.form:
            if current_user.id == 1:
                return redirect('/u/')
            if current_role=='unknown':
                return redirect(f'/p/{post}')
            pdesc=request.form.get('comment','')
            if pdesc and len(pdesc)<=250:
                date_today=datetime.today().strftime("%y.%m.%d")
                with sqlite3.connect('database/db.db') as conn:
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO comments (desc,upload_date,user_id,post_id,rating) VALUES (?, ?, ?, ?, ?)",
                                       (pdesc, date_today, current_user.id, post, 0))
                    conn.commit()
            return redirect(f'/p/{post}')
        elif 'postId' in request.form:
            what_post = request.form.get('postId', 0)
            if what_post and what_post.isnumeric() and singular_post["id"]==int(what_post) and current_user.login.lower() in singular_post['who_rem']:
                # Risky. Will remove everything regarding a specific post, including its likes/dislikes and comments
                if is_safe_folder(what_post, 'p', 'delete'):
                    with sqlite3.connect('database/db.db') as conn:
                        # Likes, Dislikes
                        cursor = conn.cursor()
                        cursor.execute('''DELETE
                                          FROM likes_dislikes_posts
                                          WHERE post_id = ?;''',
                                       (what_post,))
                        conn.commit()
                        # Posts
                        cursor = conn.cursor()
                        cursor.execute('''DELETE
                                          FROM posts
                                          WHERE id = ?;''', (what_post,))
                        conn.commit()
                        # Likes, Dislikes (comments)
                        cursor = conn.cursor()
                        cursor.execute('''DELETE
                                          FROM likes_dislikes_comments
                                          WHERE comment_id IN (SELECT id FROM comments WHERE post_id = ?);''',
                                       (what_post,))
                        conn.commit()
                        # Comments
                        cursor = conn.cursor()
                        cursor.execute('''DELETE
                                          FROM comments
                                          WHERE post_id = ?;''', (what_post,))
                        conn.commit()
                    return redirect('/?filter=popular')
                else:
                    return "Post can't be deleted."
            else:
                return redirect('/?filter=popular')
        elif 'commentId' in request.form:
            what_comment = request.form.get('commentId', 0)
            if what_comment and what_comment.isnumeric() and current_user.login.lower() in comments.get(int(what_comment),{"who_rem": {}})['who_rem']:
                # Risky. Will remove everything regarding a specific comment, including its likes/dislikes
                with sqlite3.connect('database/db.db') as conn:
                    # Likes, Dislikes
                    cursor = conn.cursor()
                    cursor.execute('''DELETE
                                        FROM likes_dislikes_comments
                                        WHERE comment_id = ?;''',
                                    (what_comment,))
                    conn.commit()
                    # Comments
                    cursor = conn.cursor()
                    cursor.execute('''DELETE
                                          FROM comments
                                          WHERE id = ?;''', (what_comment,))
                    conn.commit()
            return redirect(f'/p/{post}')

@app.route('/g/<group>',methods=['GET','POST'])
def groups(group):
    if current_user.is_anonymous:
        login_user(load_user(1))
    page = request.args.get('p', '1')
    if not page.isnumeric():
        page = '1'
    page = abs(int(page))
    if page<=0:
        page=1
    subs = {}
    with sqlite3.connect('database/db.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''SELECT GROUP_CONCAT(group_name)
                          FROM (SELECT group_name
                                FROM subscriptions
                                         INNER JOIN groups ON subscriptions.group_id = groups.id
                                WHERE user_id = ?
                                ORDER BY group_id)''', (current_user.id,))
        row = cursor.fetchone()
        if row[0]:
            subs = sorted({sub for sub in row[0].split(',') if is_safe_folder(sub, 'g', 'exist')})
    with sqlite3.connect('database/db.db') as conn:
        cursor = conn.cursor()
        cursor.execute("""SELECT groups.group_name,
                                 GROUP_CONCAT(login) AS user_ids
                          FROM groups
                                   LEFT JOIN subscriptions
                                             ON subscriptions.group_id = groups.id
                                                 AND subscriptions.role IN ('creat', 'moder')
                                   INNER JOIN users on subscriptions.user_id = users.id
                          GROUP BY groups.group_name
                          ORDER BY groups.group_name;""")
        mods_in_groups = dict(cursor.fetchall())
    with sqlite3.connect('database/db.db') as conn:
        cursor = conn.cursor()
        cursor.execute("""SELECT groups.group_name,
                                 GROUP_CONCAT(login) AS user_ids
                          FROM groups
                                   LEFT JOIN subscriptions
                                             ON subscriptions.group_id = groups.id
                                                 AND subscriptions.role IN ('user')
                                   INNER JOIN users on subscriptions.user_id = users.id
                          GROUP BY groups.group_name
                          ORDER BY groups.group_name;""")
        users_in_groups = dict(cursor.fetchall())
    with sqlite3.connect('database/db.db') as conn:
        cursor = conn.cursor()
        cursor.execute("""SELECT groups.group_name,
                                 GROUP_CONCAT(login) AS user_ids
                          FROM groups
                                   LEFT JOIN subscriptions
                                             ON subscriptions.group_id = groups.id
                                                 AND subscriptions.role IN ('moder')
                                   INNER JOIN users on subscriptions.user_id = users.id
                          GROUP BY groups.group_name
                          ORDER BY groups.group_name;""")
        only_mods_in_groups = dict(cursor.fetchall())
    if is_safe_folder(group, 'g', "exist"):
        with sqlite3.connect('database/db.db') as conn:
            cursor = conn.cursor()
            cursor.execute('''SELECT posts.id,
                                     group_name,
                                     u.login,
                                     upload_date,
                                     title, desc, attach_img, rating, (SELECT GROUP_CONCAT(login)
                                  FROM (SELECT u2.login
                                  FROM likes_dislikes_posts
                                  INNER JOIN main.users u2 on likes_dislikes_posts.user_id = u2.id
                                  WHERE post_id = posts.id AND likeorno = TRUE
                                  ORDER BY user_id)) as likes, (SELECT GROUP_CONCAT(login)
                                  FROM (SELECT u2.login
                                  FROM likes_dislikes_posts
                                  INNER JOIN main.users u2 on likes_dislikes_posts.user_id = u2.id
                                  WHERE post_id = posts.id AND likeorno = FALSE
                                  ORDER BY user_id)) AS dislikes,
                                  (rating * 1.0) / (julianday('now') -julianday('20' || REPLACE(upload_date,'.','-'))+1) AS popularity_score
                              FROM posts INNER JOIN main.groups g
                              on posts.uploader_group_id = g.id INNER JOIN main.users u on u.id = posts.uploader_user_id
                              WHERE group_name = ? ORDER BY popularity_score DESC LIMIT 5 OFFSET ?''', (group,5*(page-1)))
            rows = cursor.fetchall()
            temp_posts = { row[0]:
                {'id': row[0], 'g': row[1], 'u': row[2], 'upload_date': '.'.join(row[3].split('.')[::-1]), 'title': row[4], 'desc': row[5],
                 'attach_img': row[6], 'rating': row[7], 'liked_by': set(row[8].lower().split(',') if row[8] else []),
                 'disliked_by': set(row[9].lower().split(',') if row[9] else []), 'who_rem': set(mods_in_groups.get(row[1],'').lower().split(',')+[row[2].lower()])} for row in rows}

        posts = {id: rating_count(post.copy()) for id,post in temp_posts.items()}
    else:
        return render_template('error.html', login=current_user.login, subs=subs)
    current_group_id = None
    with sqlite3.connect('database/db.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''SELECT id
                          FROM groups
                          WHERE group_name = ?''', (group,))
        row = cursor.fetchone()
        if row:
            current_group_id = row[0]
    if current_group_id is None:
        return render_template('error.html', login=current_user.login, subs=subs)
    current_role='unknown'
    with sqlite3.connect('database/db.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''SELECT role
                                FROM subscriptions WHERE user_id=? AND group_id=?''', (current_user.id,current_group_id))
        row = cursor.fetchone()
        if row:
            current_role=row[0]
    if request.method == 'GET':
        return render_template('groups.html', login=current_user.login, subs=subs, group=group, posts=posts.values(), role=current_role, usermods_users=set(users_in_groups.get(group,'').lower().split(',') if users_in_groups.get(group,'') else {}),usermods_mods=set(only_mods_in_groups.get(group,'').lower().split(',') if only_mods_in_groups.get(group,'') else {}))
    elif request.method == 'POST':
        if current_user.is_anonymous:
            login_user(load_user(1))
            return redirect('/u/')
        if current_user.id == 1:
            return redirect('/u/')
        if 'sub' in request.form:
            if current_role=='unknown':
                with sqlite3.connect('database/db.db') as conn:
                    cursor = conn.cursor()
                    try:
                        cursor.execute("INSERT INTO subscriptions (user_id, group_id, role) VALUES (?, ?, 'user')",
                                       (current_user.id, current_group_id))
                    except sqlite3.IntegrityError:
                        return render_template('error.html', login=current_user.login, subs=subs)
                    conn.commit()
            elif current_role=='user' or current_role=='moder':
                with sqlite3.connect('database/db.db') as conn:
                    cursor = conn.cursor()
                    cursor.execute('''DELETE
                                      FROM subscriptions
                                      WHERE user_id = ?
                                        and group_id = ?;''', (current_user.id, current_group_id))
                    conn.commit()
            elif current_role=='creat':
                #Risky. Will delete everything regarding that group. Including info about likes, dislikes, comments, post, subscribers and group itself.
                if is_safe_folder(group.lower(),'g','delete'):
                    with sqlite3.connect('database/db.db') as conn:
                        # Likes, Dislikes
                        cursor = conn.cursor()
                        cursor.execute('''DELETE
                                          FROM likes_dislikes_posts
                                          WHERE post_id IN (SELECT id FROM posts WHERE uploader_group_id=?);''', (current_group_id,))
                        conn.commit()
                        # Likes, Dislikes (comments)
                        cursor = conn.cursor()
                        cursor.execute('''DELETE
                                          FROM likes_dislikes_comments
                                          WHERE comment_id IN (SELECT id FROM comments WHERE post_id IN (SELECT id FROM posts WHERE uploader_group_id=?));''',
                                       (current_group_id,))
                        conn.commit()
                        # Comments
                        cursor = conn.cursor()
                        cursor.execute('''DELETE
                                          FROM comments
                                          WHERE post_id IN (SELECT id FROM posts WHERE uploader_group_id=?);''', (current_group_id,))
                        conn.commit()
                        # Posts (remove folders)
                        cursor = conn.cursor()
                        cursor.execute('''SELECT GROUP_CONCAT(id)
                                          FROM posts
                                          WHERE uploader_group_id = ?;''', (current_group_id,))
                        posts_to_remove = cursor.fetchone()
                        posts_to_remove = posts_to_remove[0].split(',') if posts_to_remove else []
                        for postr in posts_to_remove:
                            is_safe_folder(postr,'p','delete')
                        # Posts
                        cursor = conn.cursor()
                        cursor.execute('''DELETE
                                          FROM posts
                                          WHERE uploader_group_id=?;''', (current_group_id,))
                        conn.commit()
                        # Subscribers
                        with sqlite3.connect('database/db.db') as conn:
                            cursor = conn.cursor()
                            cursor.execute('''DELETE
                                              FROM subscriptions
                                              WHERE group_id=?;''', (current_group_id,))
                            conn.commit()
                        # Group
                        with sqlite3.connect('database/db.db') as conn:
                            cursor = conn.cursor()
                            cursor.execute('''DELETE
                                              FROM groups
                                              WHERE id=?;''', (current_group_id,))
                            conn.commit()
                    return redirect('/?filter=popular')
                else:
                    return "Group can't be deleted."

            return redirect(f'/g/{group}')
        elif 'title' in request.form and 'desc' in request.form and 'attach' in request.files:
            if current_user.id == 1:
                return redirect('/u/')
            if current_role=='unknown':
                return redirect(f'/g/{group}')
            gtitle=request.form.get('title','')
            gdesc=request.form.get('desc','')
            gattach=request.files['attach']
            gattach_filename=secure_filename(gattach.filename)
            print(gattach_filename)
            if gtitle and 0<len(gtitle)<=50 and len(gdesc)<=250:
                date_today=datetime.today().strftime("%y.%m.%d")
                with sqlite3.connect('database/db.db') as conn:
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO posts (uploader_group_id,uploader_user_id,upload_date,title,desc,attach_img,rating) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                       (current_group_id, current_user.id, date_today, gtitle, gdesc, gattach_filename, 0))
                    conn.commit()
                    cursor.execute("SELECT id FROM posts WHERE uploader_group_id=? AND uploader_user_id=? AND upload_date=? AND title=? AND desc=? AND attach_img=? AND rating=? ORDER BY id DESC LIMIT 1",
                                   (current_group_id, current_user.id, date_today, gtitle, gdesc, gattach_filename, 0))
                    row = cursor.fetchone()
                    if row:
                        post_id=row[0]
                    else:
                        return redirect(f'/g/{group}')
                if is_safe_folder(str(post_id),'p','create'):
                    if gattach_filename:
                        gattach.save(os.path.join('uploads/p', str(post_id) ,gattach_filename))
                    return redirect(f'/p/{post_id}')
                else:
                    return redirect(f'/g/{group}')
            else:
                return redirect(f'/g/{group}')
        elif 'postId' in request.form:
            what_post = request.form.get('postId', 0)
            if what_post and what_post.isnumeric() and current_user.login.lower() in posts.get(int(what_post),{"who_rem": {}})['who_rem']:
                # Risky. Will remove everything regarding a specific post, including its likes/dislikes and comments
                if is_safe_folder(what_post, 'p', 'delete'):
                    with sqlite3.connect('database/db.db') as conn:
                        # Likes, Dislikes
                        cursor = conn.cursor()
                        cursor.execute('''DELETE
                                          FROM likes_dislikes_posts
                                          WHERE post_id = ?;''',
                                       (what_post,))
                        conn.commit()
                        # Posts
                        cursor = conn.cursor()
                        cursor.execute('''DELETE
                                          FROM posts
                                          WHERE id = ?;''', (what_post,))
                        conn.commit()
                        # Likes, Dislikes (comments)
                        cursor = conn.cursor()
                        cursor.execute('''DELETE
                                          FROM likes_dislikes_comments
                                          WHERE comment_id IN (SELECT id FROM comments WHERE post_id = ?);''',
                                       (what_post,))
                        conn.commit()
                        # Comments
                        cursor = conn.cursor()
                        cursor.execute('''DELETE
                                          FROM comments
                                          WHERE post_id = ?;''', (what_post,))
                        conn.commit()
                    return redirect(f'/g/{group}')
                else:
                    return "Post can't be deleted."
            else:
                return redirect(f'/g/{group}')
        elif 'banner' in request.files:
            if current_role == 'moder' or current_role == 'creat':
                file = request.files['banner']
                if file.filename == '':
                    return redirect(f'/g/{group}')
                image = img_process(file.stream,what="banner")
                filename = os.path.join('uploads/g', group.lower(), 'banner.jpg')
                image.save(filename)
                return redirect(f'/g/{group}')
            else:
                return redirect(f'/g/{group}')
        elif 'avatar' in request.files:
            if current_role == 'moder' or current_role == 'creat':
                file = request.files['avatar']
                if file.filename == '':
                    return redirect(f'/g/{group}')
                image = img_process(file.stream,what="ava")
                filename = os.path.join('uploads/g', group.lower(), 'ava.jpg')
                image.save(filename)
                return redirect(f'/g/{group}')
            else:
                return redirect(f'/g/{group}')
        elif 'usermods' in request.form:
            if current_role == 'creat':
                new_mods=set(request.form.getlist('usermods'))
                actual_mods = list(new_mods - set(only_mods_in_groups.get(group, '').lower().split(',')))
                turn_to_users = list(set(only_mods_in_groups.get(group, '').lower().split(',')) - new_mods)
                with sqlite3.connect('database/db.db') as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        f"UPDATE subscriptions set role='moder' WHERE group_id IN (SELECT id FROM groups WHERE groups.group_name=?) AND role NOT IN ('moder','creat') AND user_id IN (SELECT id FROM users WHERE users.login IN ({', '.join('?' for _ in actual_mods)}))",
                        [group] + actual_mods)
                    conn.commit()
                with sqlite3.connect('database/db.db') as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        f"UPDATE subscriptions set role='user' WHERE group_id IN (SELECT id FROM groups WHERE groups.group_name=?) AND role NOT IN ('user','creat') AND user_id IN (SELECT id FROM users WHERE users.login IN ({', '.join('?' for _ in turn_to_users)}))",
                        [group] + turn_to_users)
                    conn.commit()
            return redirect(f'/g/{group}')


@app.route('/u/<login>', methods=['GET','POST'])
def profile(login):
    if current_user.is_anonymous:
        login_user(load_user(1))
    if current_user.id==1 and login.lower()=='anonymous':
        return redirect('/u/')

    page = request.args.get('p','1')
    if not page.isnumeric():
        page='1'
    page=abs(int(page))
    if page<=0:
        page=1
    subs = {}
    with sqlite3.connect('database/db.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''SELECT GROUP_CONCAT(group_name)
                          FROM (SELECT group_name
                                FROM subscriptions
                                         INNER JOIN groups ON subscriptions.group_id = groups.id
                                WHERE user_id = ?
                                ORDER BY group_id)''', (current_user.id,))
        row = cursor.fetchone()
        if row[0]:
            subs = sorted({sub for sub in row[0].split(',') if is_safe_folder(sub, 'g', 'exist')})
    with sqlite3.connect('database/db.db') as conn:
        cursor = conn.cursor()
        cursor.execute("""SELECT groups.group_name,
                                 GROUP_CONCAT(login) AS user_ids
                          FROM groups
                                   LEFT JOIN subscriptions
                                             ON subscriptions.group_id = groups.id
                                                 AND subscriptions.role IN ('creat', 'moder')
                                   INNER JOIN users on subscriptions.user_id = users.id
                          GROUP BY groups.group_name
                          ORDER BY groups.group_name;""")
        mods_in_groups = dict(cursor.fetchall())
    if is_safe_folder(login, 'u', "exist"):
        with sqlite3.connect('database/db.db') as conn:
            cursor = conn.cursor()
            cursor.execute('''SELECT posts.id,
                                     group_name,
                                     u.login,
                                     upload_date,
                                     title, desc, attach_img, rating, (SELECT GROUP_CONCAT(login)
                                  FROM (SELECT u2.login
                                  FROM likes_dislikes_posts
                                  INNER JOIN main.users u2 on likes_dislikes_posts.user_id = u2.id
                                  WHERE post_id = posts.id AND likeorno = TRUE
                                  ORDER BY user_id)) as likes, (SELECT GROUP_CONCAT(login)
                                  FROM (SELECT u2.login
                                  FROM likes_dislikes_posts
                                  INNER JOIN main.users u2 on likes_dislikes_posts.user_id = u2.id
                                  WHERE post_id = posts.id AND likeorno = FALSE
                                  ORDER BY user_id)) AS dislikes,
                                  (rating * 1.0) / (julianday('now') -julianday('20' || REPLACE(upload_date,'.','-'))+1) AS popularity_score
                              FROM posts INNER JOIN main.groups g
                              on posts.uploader_group_id = g.id INNER JOIN main.users u on u.id = posts.uploader_user_id
                              WHERE u.login = ? ORDER BY popularity_score DESC''', (login,))
            how_many_are_there_posts = len(cursor.fetchall())
            cursor.execute('''SELECT posts.id,
                                     group_name,
                                     u.login,
                                     upload_date,
                                     title, desc, attach_img, rating, (SELECT GROUP_CONCAT(login)
                                  FROM (SELECT u2.login
                                  FROM likes_dislikes_posts
                                  INNER JOIN main.users u2 on likes_dislikes_posts.user_id = u2.id
                                  WHERE post_id = posts.id AND likeorno = TRUE
                                  ORDER BY user_id)) as likes, (SELECT GROUP_CONCAT(login)
                                  FROM (SELECT u2.login
                                  FROM likes_dislikes_posts
                                  INNER JOIN main.users u2 on likes_dislikes_posts.user_id = u2.id
                                  WHERE post_id = posts.id AND likeorno = FALSE
                                  ORDER BY user_id)) AS dislikes,
                                  (rating * 1.0) / (julianday('now') -julianday('20' || REPLACE(upload_date,'.','-'))+1) AS popularity_score
                              FROM posts INNER JOIN main.groups g
                              on posts.uploader_group_id = g.id INNER JOIN main.users u on u.id = posts.uploader_user_id
                              WHERE u.login = ? ORDER BY popularity_score DESC LIMIT 5 OFFSET ?''', (login,5*(page-1)))
            rows = cursor.fetchall()
            temp_posts = { row[0]:
                {'id': row[0], 'g': row[1], 'u': row[2], 'upload_date': '.'.join(row[3].split('.')[::-1]), 'title': row[4], 'desc': row[5],
                 'attach_img': row[6], 'rating': row[7], 'liked_by': set(row[8].lower().split(',') if row[8] else []),
                 'disliked_by': set(row[9].lower().split(',') if row[9] else []), 'who_rem': set(mods_in_groups.get(row[1],'').lower().split(',')+[row[2].lower()])} for row in rows}

        posts = {id: rating_count(post.copy()) for id,post in temp_posts.items()}
    else:
        return render_template('error.html', login=current_user.login, subs=subs)
    if request.method == 'GET':
        return render_template('profile.html', clogin=current_user.login, cemail=current_user.email, login=login, subs=subs, posts=posts.values(), error=False, page=page, total_pages=how_many_are_there_posts)
    elif request.method == 'POST':
        if current_user.is_anonymous:
            login_user(load_user(1))
            return redirect('/u/')
        if current_user.id == 1:
            return redirect('/u/')
        if 'email' in request.form:
            email=request.form.get('email','')
            new_pass=request.form.get('password','')
            if new_pass:
                if email and new_pass and re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$',email) is not None and (len(new_pass)>=8 and re.search(r"^[A-Za-z0-9!@#$%^&*()-_=+\[\]{}|;:'\",.<>/?~]+$",new_pass)):
                    if current_user.id==1:
                        return redirect('/u/')
                    if not current_user.check_password(new_pass) and current_user.email!=email:
                        with sqlite3.connect('database/db.db') as conn:
                            cursor = conn.cursor()
                            try:
                                cursor.execute('''UPDATE users
                                                  SET email = ?, password = ?
                                                  WHERE id = ?;''', (email, ph.hash(new_pass),current_user.id))
                            except sqlite3.IntegrityError:
                                return render_template('profile.html', clogin=current_user.login, cemail=current_user.email, login=login, subs=subs, posts=posts.values(), error=True, page=page, total_pages=how_many_are_there_posts)
                            conn.commit()
                            login_user(load_user(current_user.id))
                            return redirect(f'/u/{login}')
                    elif current_user.email!=email:
                        with sqlite3.connect('database/db.db') as conn:
                            cursor = conn.cursor()
                            try:
                                cursor.execute('''UPDATE users
                                                  SET email = ?
                                                  WHERE id = ?;''', (email,current_user.id))
                            except sqlite3.IntegrityError:
                                return render_template('profile.html', clogin=current_user.login, cemail=current_user.email, login=login, subs=subs, posts=posts.values(), error=True, page=page, total_pages=how_many_are_there_posts)
                            conn.commit()
                            login_user(load_user(current_user.id))
                            return redirect(f'/u/{login}')
                    elif not current_user.check_password(new_pass):
                        with sqlite3.connect('database/db.db') as conn:
                            cursor = conn.cursor()
                            try:
                                cursor.execute('''UPDATE users
                                                  SET password = ?
                                                  WHERE id = ?;''', (ph.hash(new_pass),current_user.id))
                            except sqlite3.IntegrityError:
                                return render_template('profile.html', clogin=current_user.login, cemail=current_user.email, login=login, subs=subs, posts=posts.values(), error=True, page=page, total_pages=how_many_are_there_posts)
                            conn.commit()
                            login_user(load_user(current_user.id))
                            return redirect(f'/u/{login}')
                    else:
                        return render_template('profile.html', clogin=current_user.login, cemail=current_user.email,
                                               login=login, subs=subs, posts=posts.values(), error=False, page=page, total_pages=how_many_are_there_posts)
                else:
                    return render_template('profile.html', clogin=current_user.login, cemail=current_user.email, login=login,
                                           subs=subs, posts=posts.values(), error=True, page=page, total_pages=how_many_are_there_posts)
            else:
                if email and re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$',email) is not None and (len(new_pass)>=8 and re.search(r"^[A-Za-z0-9!@#$%^&*()-_=+\[\]{}|;:'\",.<>/?~]+$",new_pass)):
                    if current_user.id==1:
                        return redirect('/u/')
                    if current_user.email!=email:
                        with sqlite3.connect('database/db.db') as conn:
                            cursor = conn.cursor()
                            try:
                                cursor.execute('''UPDATE users
                                                  SET email = ?
                                                  WHERE id = ?;''', (email, current_user.id))
                            except sqlite3.IntegrityError:
                                return render_template('profile.html', clogin=current_user.login, cemail=current_user.email, login=login, subs=subs, posts=posts.values(), error=True, page=page, total_pages=how_many_are_there_posts)
                            conn.commit()
                            login_user(load_user(current_user.id))
                            return redirect(f'/u/{login}')
                    else:
                        return render_template('profile.html', clogin=current_user.login, cemail=current_user.email,
                                               login=login, subs=subs, posts=posts.values(), error=False, page=page, total_pages=how_many_are_there_posts)
                else:
                    return render_template('profile.html', clogin=current_user.login, cemail=current_user.email, login=login,
                                           subs=subs, posts=posts.values(), error=True, page=page, total_pages=how_many_are_there_posts)
        elif 'avatar' in request.files:
            file = request.files['avatar']
            if file.filename == '':
                return render_template('profile.html', clogin=current_user.login, cemail=current_user.email, login=login, subs=subs, posts=posts.values(), error=True, page=page, total_pages=how_many_are_there_posts)
            image = img_process(file.stream,what="ava")
            filename = os.path.join('uploads/u', current_user.login.lower(), 'ava.jpg')
            image.save(filename)
            return redirect(f'/u/{login}')
        elif 'logout' in request.form:
            logout_user()
            return redirect('/u/')
        elif 'postId' in request.form:
            what_post = request.form.get('postId', 0)
            if what_post and what_post.isnumeric() and current_user.login.lower() in posts.get(int(what_post),{"who_rem": {}})['who_rem']:
                # Risky. Will remove everything regarding a specific post, including its likes/dislikes and comments
                if is_safe_folder(what_post, 'p', 'delete'):
                    with sqlite3.connect('database/db.db') as conn:
                        # Likes, Dislikes
                        cursor = conn.cursor()
                        cursor.execute('''DELETE
                                          FROM likes_dislikes_posts
                                          WHERE post_id = ?;''',
                                       (what_post,))
                        conn.commit()
                        # Posts
                        cursor = conn.cursor()
                        cursor.execute('''DELETE
                                          FROM posts
                                          WHERE id = ?;''', (what_post,))
                        conn.commit()
                        # Likes, Dislikes (comments)
                        cursor = conn.cursor()
                        cursor.execute('''DELETE
                                          FROM likes_dislikes_comments
                                          WHERE comment_id IN (SELECT id FROM comments WHERE post_id = ?);''',
                                       (what_post,))
                        conn.commit()
                        # Comments
                        cursor = conn.cursor()
                        cursor.execute('''DELETE
                                          FROM comments
                                          WHERE post_id = ?;''', (what_post,))
                        conn.commit()
                    return redirect(f'/u/{login}')
                else:
                    return "Post can't be deleted."
            else:
                return redirect(f'/u/{login}')
        else:
            return redirect(f'/u/{login}')

@app.route('/', methods=['GET','POST'])
def index():
    query = request.args.get('q', '').lower().strip()
    category = request.args.get('c','').lower().strip()
    if category not in ['','users','posts','groups']:
        category=''

    page = request.args.get('p','1')
    if not page.isnumeric():
        page='1'
    page=abs(int(page))
    if page<=0:
        page=1
    filter = request.args.get('filter', '').lower()
    subs = {}
    if current_user.is_anonymous:
        login_user(load_user(1))
        if filter == '':
            return redirect('/?filter=popular')
    else:
        with sqlite3.connect('database/db.db') as conn:
            cursor = conn.cursor()
            cursor.execute('''SELECT GROUP_CONCAT(group_name)
                              FROM (SELECT group_name
                                    FROM subscriptions
                                             INNER JOIN groups ON subscriptions.group_id = groups.id
                                    WHERE user_id = ?
                                    ORDER BY group_id)''', (current_user.id,))
            row = cursor.fetchone()
            if row[0]:
                subs = sorted({sub for sub in row[0].split(',') if is_safe_folder(sub, 'g', 'exist')})
    with sqlite3.connect('database/db.db') as conn:
        cursor = conn.cursor()
        cursor.execute("""SELECT groups.group_name,
                                 GROUP_CONCAT(login) AS user_ids
                          FROM groups
                                   LEFT JOIN subscriptions
                                             ON subscriptions.group_id = groups.id
                                                 AND subscriptions.role IN ('creat', 'moder')
                                   INNER JOIN users on subscriptions.user_id = users.id
                          GROUP BY groups.group_name
                          ORDER BY groups.group_name;""")
        mods_in_groups = dict(cursor.fetchall())
    search_users={}
    search_groups={}
    posts={}
    how_many_are_there_posts = 0
    if query!='' and (category=='' or category == 'users'):
        with sqlite3.connect('database/db.db') as conn:
            cursor = conn.cursor()
            query=re.sub(r"\s+","",query)
            cursor.execute('SELECT login FROM users WHERE login LIKE :search', {"search": f'%{query}%'})
            how_many_are_there_posts = len(cursor.fetchall())
            cursor.execute('SELECT login FROM users WHERE login LIKE :search LIMIT 5 OFFSET :offset', {"search": f'%{query}%', "offset": 5*(page-1)})
            search_users = set(cursor.fetchall())
    if query!='' and (category=='' or category=='groups'):
        with sqlite3.connect('database/db.db') as conn:
            cursor = conn.cursor()
            query=re.sub(r"\s+","",query)
            cursor.execute('SELECT group_name FROM groups WHERE group_name LIKE :search', {"search": f'%{query}%'})
            how_many_are_there_posts = len(cursor.fetchall())
            cursor.execute('SELECT group_name FROM groups WHERE group_name LIKE :search LIMIT 5 OFFSET :offset', {"search": f'%{query}%', "offset": 5*(page-1)})
            search_groups = set(cursor.fetchall())
    if category=='' or category=='posts':
        sql_command='''SELECT posts.id,
                                     group_name,
                                     u.login,
                                     upload_date,
                                     title, desc, attach_img, rating, (SELECT GROUP_CONCAT(login)
                                  FROM (SELECT u2.login
                                  FROM likes_dislikes_posts
                                  INNER JOIN main.users u2 on likes_dislikes_posts.user_id = u2.id
                                  WHERE post_id = posts.id AND likeorno = TRUE
                                  ORDER BY user_id)) as likes, (SELECT GROUP_CONCAT(login)
                                  FROM (SELECT u2.login
                                  FROM likes_dislikes_posts
                                  INNER JOIN main.users u2 on likes_dislikes_posts.user_id = u2.id
                                  WHERE post_id = posts.id AND likeorno = FALSE
                                  ORDER BY user_id)) AS dislikes,
                                  (rating * 1.0) / (julianday('now') -julianday('20' || REPLACE(upload_date,'.','-'))+1) AS popularity_score
                              FROM posts INNER JOIN main.groups g
                              on posts.uploader_group_id = g.id INNER JOIN main.users u on u.id = posts.uploader_user_id '''
        if query!='':
            sql_command+="WHERE title LIKE :search OR desc LIKE :search OR attach_img LIKE :search ORDER BY popularity_score DESC "
        elif filter == '':
            sql_command+=f'WHERE group_name IN ({", ".join("?" for _ in subs)}) '
        elif filter == 'popular':
            sql_command+='ORDER BY popularity_score DESC '
        elif filter == 'latest':
            sql_command+='ORDER BY upload_date DESC, rating DESC '
        with sqlite3.connect('database/db.db') as conn:
            cursor = conn.cursor()
            if filter == '' and query == '':
                cursor.execute(sql_command, subs)
            else:
                if query=='':
                    cursor.execute(sql_command)
                else:
                    cursor.execute(sql_command, {"search": f'%{query}%'})
            rows = cursor.fetchall()
            how_many_are_there_posts=len(rows)
            sql_command+=f'LIMIT 5 OFFSET {5*(page-1)}'
            if filter == '' and query == '':
                cursor.execute(sql_command, subs)
            else:
                if query=='':
                    cursor.execute(sql_command)
                else:
                    cursor.execute(sql_command, {"search": f'%{query}%'})
            rows = cursor.fetchall()
            temp_posts = { row[0]:
                {'id': row[0], 'g': row[1], 'u': row[2], 'upload_date': '.'.join(row[3].split('.')[::-1]), 'title': row[4], 'desc': row[5],
                 'attach_img': row[6], 'rating': row[7], 'liked_by': set(row[8].lower().split(',') if row[8] else []),
                 'disliked_by': set(row[9].lower().split(',') if row[9] else []), 'who_rem': set(mods_in_groups.get(row[1],'').lower().split(',')+[row[2].lower()])} for row in rows}

        posts = {id: rating_count(post.copy()) for id,post in temp_posts.items()}

    if request.method=='GET':
        return render_template('home_with_style.html', login=current_user.login, filter=filter, subs=subs, posts=posts.values(), search_users=search_users,search_groups=search_groups, query=query, page=page, category=category, total_pages=how_many_are_there_posts)
    elif request.method=='POST':
        if current_user.is_anonymous:
            login_user(load_user(1))
            return redirect('/u/')
        if current_user.id == 1:
            return redirect('/u/')
        if 'postId' in request.form:
            what_post = request.form.get('postId',0)
            if what_post and what_post.isnumeric() and current_user.login.lower() in posts.get(int(what_post),{"who_rem": {}})['who_rem']:
                #Risky. Will remove everything regarding a specific post, including its likes/dislikes and comments
                if is_safe_folder(what_post, 'p', 'delete'):
                    with sqlite3.connect('database/db.db') as conn:
                        # Likes, Dislikes
                        cursor = conn.cursor()
                        cursor.execute('''DELETE
                                          FROM likes_dislikes_posts
                                          WHERE post_id = ?;''',
                                       (what_post,))
                        conn.commit()
                        # Posts
                        cursor = conn.cursor()
                        cursor.execute('''DELETE
                                          FROM posts
                                          WHERE id = ?;''', (what_post,))
                        conn.commit()
                        # Likes, Dislikes (comments)
                        cursor = conn.cursor()
                        cursor.execute('''DELETE
                                          FROM likes_dislikes_comments
                                          WHERE comment_id IN (SELECT id FROM comments WHERE post_id = ?);''',
                                       (what_post,))
                        conn.commit()
                        # Comments
                        cursor = conn.cursor()
                        cursor.execute('''DELETE
                                          FROM comments
                                          WHERE post_id = ?;''', (what_post,))
                        conn.commit()
                    return redirect('/?filter=popular')
                else:
                    return "Post can't be deleted."
            else:
                return redirect('/?filter=popular')
        else:
            return redirect('/?filter=popular')

@app.route('/uploads/<folder0>/<folder1>/<filename>')
def serve_user_file(folder0,folder1,filename):
    return send_from_directory(os.path.join(UPLOAD_FOLDER, folder0, folder1), filename)

@app.errorhandler(404)
def error(e):
    if current_user.is_anonymous:
        login_user(load_user(1))
    subs = {}
    with sqlite3.connect('database/db.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''SELECT GROUP_CONCAT(group_name)
                          FROM (SELECT group_name
                                FROM subscriptions
                                         INNER JOIN groups ON subscriptions.group_id = groups.id
                                WHERE user_id = ?
                                ORDER BY group_id)''', (current_user.id,))
        row = cursor.fetchone()
        if row[0]:
            subs = sorted({sub for sub in row[0].split(',') if is_safe_folder(sub, 'g', 'exist')})
    return render_template('error.html', login=current_user.login, subs=subs)


if __name__ == '__main__':
    socketio.run(app, allow_unsafe_werkzeug=True)
