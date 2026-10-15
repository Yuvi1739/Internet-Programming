import os
import sqlite3
from datetime import date, timedelta
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, session, flash, g, send_from_directory

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "library.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "ppt", "pptx"}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("LIBRARY_SECRET_KEY", "change-this-secret-key-for-local-development")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
FINE_PER_DAY = 5  # Change the daily overdue fine here (₹5/day by default).


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'student',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS books (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        author TEXT NOT NULL,
        isbn TEXT UNIQUE,
        category TEXT,
        publication_year INTEGER,
        total_copies INTEGER NOT NULL DEFAULT 1 CHECK(total_copies >= 0),
        available_copies INTEGER NOT NULL DEFAULT 1 CHECK(available_copies >= 0)
    );
    CREATE TABLE IF NOT EXISTS borrow_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id),
        book_id INTEGER NOT NULL REFERENCES books(id),
        issue_date TEXT NOT NULL,
        due_date TEXT NOT NULL,
        return_date TEXT,
        status TEXT NOT NULL DEFAULT 'Issued'
    );
    CREATE TABLE IF NOT EXISTS study_materials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        year TEXT NOT NULL,
        semester TEXT NOT NULL,
        filename TEXT NOT NULL,
        uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS contact_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER REFERENCES users(id),
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        subject TEXT NOT NULL,
        message TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """)
    admin = db.execute("SELECT id FROM users WHERE email = ?", ("admin@library.local",)).fetchone()
    if not admin:
        db.execute(
            "INSERT INTO users (name,email,password_hash,role) VALUES (?,?,?,?)",
            ("Library Admin", "admin@library.local", generate_password_hash("Admin@123"), "admin")
        )
    db.commit()
    db.close()


def login_required(role=None):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "user_id" not in session:
                flash("Please log in to continue.", "warning")
                return redirect(url_for("login"))
            if role and session.get("role") != role:
                flash("You do not have permission to access that page.", "error")
                return redirect(url_for("index"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def fine_for(record):
    if record["status"] == "Returned":
        end_date = date.fromisoformat(record["return_date"])
    else:
        end_date = date.today()
    due = date.fromisoformat(record["due_date"])
    return max(0, (end_date - due).days) * FINE_PER_DAY


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/")
def index():
    db = get_db()
    q = request.args.get("q", "").strip()
    if q:
        books = db.execute("""
            SELECT * FROM books
            WHERE title LIKE ? OR author LIKE ? OR isbn LIKE ? OR category LIKE ?
            ORDER BY title
        """, tuple([f"%{q}%"] * 4)).fetchall()
    else:
        books = db.execute("SELECT * FROM books ORDER BY title LIMIT 30").fetchall()
    return render_template("index.html", books=books, q=q)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or not email or len(password) < 8:
            flash("Enter your name and email, and use a password of at least 8 characters.", "error")
            return render_template("register.html")
        try:
            get_db().execute(
                "INSERT INTO users (name,email,password_hash,role) VALUES (?,?,?,?)",
                (name, email, generate_password_hash(password), "student")
            )
            get_db().commit()
            flash("Registration successful. You can now log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("That email address is already registered.", "error")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session.update(user_id=user["id"], name=user["name"], role=user["role"])
            flash(f"Welcome, {user['name']}!", "success")
            return redirect(url_for("admin_dashboard" if user["role"] == "admin" else "student_dashboard"))
        flash("Invalid email or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))


@app.route("/books/<int:book_id>")
def book_detail(book_id):
    book = get_db().execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if not book:
        flash("Book not found.", "error")
        return redirect(url_for("index"))
    return render_template("book_detail.html", book=book)


@app.route("/student")
@login_required("student")
def student_dashboard():
    db = get_db()
    records = db.execute("""
        SELECT br.*, b.title, b.author FROM borrow_records br
        JOIN books b ON b.id = br.book_id
        WHERE br.user_id = ? ORDER BY br.issue_date DESC
    """, (session["user_id"],)).fetchall()
    history = [{"record": r, "fine": fine_for(r)} for r in records]
    total_fine = sum(x["fine"] for x in history if x["record"]["status"] == "Issued")
    return render_template("student_dashboard.html", history=history, total_fine=total_fine)


@app.route("/admin")
@login_required("admin")
def admin_dashboard():
    db = get_db()
    stats = {
        "books": db.execute("SELECT COUNT(*) FROM books").fetchone()[0],
        "students": db.execute("SELECT COUNT(*) FROM users WHERE role='student'").fetchone()[0],
        "issued": db.execute("SELECT COUNT(*) FROM borrow_records WHERE status='Issued'").fetchone()[0],
        "overdue": db.execute("SELECT COUNT(*) FROM borrow_records WHERE status='Issued' AND due_date < ?", (date.today().isoformat(),)).fetchone()[0],
    }
    records = db.execute("""
        SELECT br.*, u.name AS student_name, b.title AS book_title
        FROM borrow_records br JOIN users u ON u.id=br.user_id JOIN books b ON b.id=br.book_id
        ORDER BY br.issue_date DESC LIMIT 15
    """).fetchall()
    return render_template("admin_dashboard.html", stats=stats, records=records)


@app.route("/admin/books", methods=["GET", "POST"])
@login_required("admin")
def manage_books():
    db = get_db()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        author = request.form.get("author", "").strip()
        isbn = request.form.get("isbn", "").strip() or None
        category = request.form.get("category", "").strip()
        year_raw = request.form.get("publication_year", "").strip()
        qty_raw = request.form.get("total_copies", "1").strip()
        try:
            year = int(year_raw) if year_raw else None
            qty = int(qty_raw)
            if not title or not author or qty < 0:
                raise ValueError()
            db.execute("""INSERT INTO books(title,author,isbn,category,publication_year,total_copies,available_copies)
                          VALUES(?,?,?,?,?,?,?)""", (title, author, isbn, category, year, qty, qty))
            db.commit()
            flash("Book added successfully.", "success")
            return redirect(url_for("manage_books"))
        except (ValueError, sqlite3.IntegrityError):
            flash("Check the book details. ISBN must be unique and quantity must be zero or more.", "error")
    books = db.execute("SELECT * FROM books ORDER BY title").fetchall()
    return render_template("manage_books.html", books=books)


@app.route("/admin/books/<int:book_id>/edit", methods=["GET", "POST"])
@login_required("admin")
def edit_book(book_id):
    db = get_db()
    book = db.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
    if not book:
        flash("Book not found.", "error")
        return redirect(url_for("manage_books"))
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        author = request.form.get("author", "").strip()
        isbn = request.form.get("isbn", "").strip() or None
        category = request.form.get("category", "").strip()
        year_raw = request.form.get("publication_year", "").strip()
        qty_raw = request.form.get("total_copies", "").strip()
        try:
            year = int(year_raw) if year_raw else None
            qty = int(qty_raw)
            currently_out = book["total_copies"] - book["available_copies"]
            if not title or not author or qty < currently_out:
                raise ValueError()
            available = qty - currently_out
            db.execute("""UPDATE books SET title=?,author=?,isbn=?,category=?,publication_year=?,
                          total_copies=?,available_copies=? WHERE id=?""",
                       (title, author, isbn, category, year, qty, available, book_id))
            db.commit()
            flash("Book updated.", "success")
            return redirect(url_for("manage_books"))
        except (ValueError, sqlite3.IntegrityError):
            flash("Invalid details. Quantity cannot be lower than copies currently issued, and ISBN must be unique.", "error")
    return render_template("edit_book.html", book=book)


@app.route("/admin/books/<int:book_id>/delete", methods=["POST"])
@login_required("admin")
def delete_book(book_id):
    db = get_db()
    count = db.execute("SELECT COUNT(*) FROM borrow_records WHERE book_id=?", (book_id,)).fetchone()[0]
    if count:
        flash("This book has borrowing history and cannot be deleted. You can update its quantity instead.", "error")
    else:
        db.execute("DELETE FROM books WHERE id=?", (book_id,))
        db.commit()
        flash("Book deleted.", "success")
    return redirect(url_for("manage_books"))


@app.route("/admin/issue", methods=["GET", "POST"])
@login_required("admin")
def issue_book():
    db = get_db()
    if request.method == "POST":
        try:
            user_id = int(request.form["user_id"])
            book_id = int(request.form["book_id"])
            days = int(request.form.get("days", "14"))
            if days < 1 or days > 90:
                raise ValueError()
            student = db.execute("SELECT id FROM users WHERE id=? AND role='student'", (user_id,)).fetchone()
            book = db.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
            if not student or not book or book["available_copies"] < 1:
                flash("Select a valid student and an available book.", "error")
            else:
                issue_date = date.today()
                due_date = issue_date + timedelta(days=days)
                db.execute("INSERT INTO borrow_records(user_id,book_id,issue_date,due_date,status) VALUES(?,?,?,?,?)",
                           (user_id, book_id, issue_date.isoformat(), due_date.isoformat(), "Issued"))
                db.execute("UPDATE books SET available_copies=available_copies-1 WHERE id=?", (book_id,))
                db.commit()
                flash(f"Book issued. Due date: {due_date.isoformat()}", "success")
                return redirect(url_for("issue_book"))
        except (ValueError, KeyError):
            flash("Please provide valid issue details.", "error")
    students = db.execute("SELECT id,name,email FROM users WHERE role='student' ORDER BY name").fetchall()
    books = db.execute("SELECT id,title,author,available_copies FROM books WHERE available_copies>0 ORDER BY title").fetchall()
    records = db.execute("""SELECT br.*,u.name AS student_name,b.title AS book_title
        FROM borrow_records br JOIN users u ON u.id=br.user_id JOIN books b ON b.id=br.book_id
        WHERE br.status='Issued' ORDER BY br.due_date""").fetchall()
    return render_template("issue_book.html", students=students, books=books, records=records, today=date.today().isoformat(),
                           fines={r["id"]: fine_for(r) for r in records})


@app.route("/admin/return/<int:record_id>", methods=["POST"])
@login_required("admin")
def return_book(record_id):
    db = get_db()
    record = db.execute("SELECT * FROM borrow_records WHERE id=? AND status='Issued'", (record_id,)).fetchone()
    if not record:
        flash("Active borrowing record not found.", "error")
    else:
        return_date = date.today().isoformat()
        fine = max(0, (date.today() - date.fromisoformat(record["due_date"])).days) * FINE_PER_DAY
        db.execute("UPDATE borrow_records SET status='Returned', return_date=? WHERE id=?", (return_date, record_id))
        db.execute("UPDATE books SET available_copies=available_copies+1 WHERE id=?", (record["book_id"],))
        db.commit()
        flash(f"Book returned successfully. Fine due: ₹{fine}.", "success")
    return redirect(url_for("issue_book"))


@app.route("/materials", methods=["GET", "POST"])
def materials():
    db = get_db()
    year = request.args.get("year", "").strip()
    semester = request.args.get("semester", "").strip()
    sql = "SELECT * FROM study_materials WHERE 1=1"
    params = []
    if year:
        sql += " AND year=?"
        params.append(year)
    if semester:
        sql += " AND semester=?"
        params.append(semester)
    sql += " ORDER BY year,semester,title"
    rows = db.execute(sql, params).fetchall()
    return render_template("materials.html", materials=rows, year=year, semester=semester)


@app.route("/admin/materials", methods=["GET", "POST"])
@login_required("admin")
def manage_materials():
    db = get_db()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        year = request.form.get("year", "").strip()
        semester = request.form.get("semester", "").strip()
        file = request.files.get("file")
        if not title or not year or not semester or not file or not file.filename or not allowed_file(file.filename):
            flash("Enter title, year, semester and upload a PDF/Office document.", "error")
        else:
            safe_name = secure_filename(file.filename)
            stored_name = f"{date.today().strftime('%Y%m%d')}_{os.urandom(4).hex()}_{safe_name}"
            file.save(os.path.join(UPLOAD_FOLDER, stored_name))
            db.execute("INSERT INTO study_materials(title,year,semester,filename) VALUES(?,?,?,?)",
                       (title, year, semester, stored_name))
            db.commit()
            flash("Study material uploaded.", "success")
            return redirect(url_for("manage_materials"))
    rows = db.execute("SELECT * FROM study_materials ORDER BY year,semester,title").fetchall()
    return render_template("manage_materials.html", materials=rows)


@app.route("/admin/materials/<int:material_id>/delete", methods=["POST"])
@login_required("admin")
def delete_material(material_id):
    db = get_db()
    material = db.execute("SELECT * FROM study_materials WHERE id=?", (material_id,)).fetchone()
    if material:
        path = os.path.join(UPLOAD_FOLDER, material["filename"])
        if os.path.isfile(path):
            os.remove(path)
        db.execute("DELETE FROM study_materials WHERE id=?", (material_id,))
        db.commit()
        flash("Material deleted.", "success")
    return redirect(url_for("manage_materials"))


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    # Study materials are available to signed-in users only.
    if "user_id" not in session:
        flash("Please log in to access study materials.", "warning")
        return redirect(url_for("login"))
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=False)


@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        subject = request.form.get("subject", "").strip()
        message = request.form.get("message", "").strip()
        if not all([name, email, subject, message]):
            flash("Please complete all fields.", "error")
        else:
            get_db().execute("INSERT INTO contact_messages(user_id,name,email,subject,message) VALUES(?,?,?,?,?)",
                             (session.get("user_id"), name, email, subject, message))
            get_db().commit()
            flash("Your message has been sent to the library team.", "success")
            return redirect(url_for("contact"))
    return render_template("contact.html")


@app.errorhandler(413)
def file_too_large(_error):
    flash("File is too large. Maximum upload size is 20 MB.", "error")
    return redirect(url_for("manage_materials"))


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
