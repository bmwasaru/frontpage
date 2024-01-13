from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    login_required,
    logout_user,
    current_user,
)
from flask_migrate import Migrate
from flask_wtf import FlaskForm
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from datetime import datetime
from logging.handlers import RotatingFileHandler
import logging
import os
import markdown
import pycountry
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, EqualTo, ValidationError

load_dotenv()  # Load environment variables from .env file

# Initialize Flask app and database
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///blog.db"
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "default-secret-key")

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)


# User model
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True)
    password_hash = db.Column(db.String(100))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)

    def __repr__(self):
        return "<Category %r>" % self.name


# Association table for the many-to-many relationship
article_categories = db.Table(
    "article_categories",
    db.Column("article_id", db.Integer, db.ForeignKey("article.id"), primary_key=True),
    db.Column(
        "category_id", db.Integer, db.ForeignKey("category.id"), primary_key=True
    ),
)


# Define the Article model
class Article(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    author = db.Column(db.String(50), nullable=False)
    publish_date = db.Column(db.DateTime, default=datetime.utcnow)
    country = db.Column(db.String(50))  # Store the selected country
    download_link = db.Column(db.String(255))  # URL to the download link
    article_type = db.Column(db.String(50))
    source = db.Column(db.String(255))
    categories = db.relationship(
        "Category",
        secondary=article_categories,
        lazy="subquery",
        backref=db.backref("articles", lazy=True),
    )

    def __repr__(self):
        return "<Article %r>" % self.title


class RegistrationForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    confirm_password = PasswordField(
        "Confirm Password", validators=[DataRequired(), EqualTo("password")]
    )
    submit = SubmitField("Register")

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError(
                "That username is already taken. Please choose a different one."
            )


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@login_manager.unauthorized_handler
def unauthorized():
    # Flash a message to inform the user
    flash("You need to be logged in to view that page.")
    return redirect(url_for("home"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("home"))

    form = RegistrationForm()
    if form.validate_on_submit():
        hashed_password = generate_password_hash(form.password.data)
        user = User(username=form.username.data, password_hash=hashed_password)
        db.session.add(user)
        db.session.commit()
        flash("Your account has been created! You are now able to log in", "success")
        return redirect(url_for("login"))
    return render_template("register.html", title="Register", form=form)


# Login route
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for("home"))
        flash("Invalid username or password")

    return render_template("login.html")


# Logout route
@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("home"))


# Home route
@app.route("/")
def home():
    articles = Article.query.order_by(Article.publish_date.desc()).all()
    # Convert Markdown to HTML for each article
    for article in articles:
        article.content_html = markdown.markdown(article.content)
    return render_template("home.html", articles=articles)


# Protect the publish route
@app.route("/publish", methods=["GET", "POST"])
@login_required
def publish():
    categories = Category.query.all()
    countries = [country.name for country in pycountry.countries]
    article_types = ["Hack", "Leak", "News", "Opinion", "Other"]

    if request.method == "POST":
        article_title = request.form["title"]
        article_content = request.form["content"]
        article_countries = request.form.getlist(
            "countries"
        )  # List of selected countries
        article_country = ", ".join(article_countries)  # Convert list to string
        article_type = request.form["type"]
        article_download_link = request.form["download_link"]

        article_author = current_user.username

        new_article = Article(
            title=article_title,
            content=article_content,
            author=article_author,
            country=article_country,
            article_type=article_type,
            download_link=article_download_link,
        )
        selected_category_ids = request.form.getlist("categories")
        selected_categories = Category.query.filter(
            Category.id.in_(selected_category_ids)
        ).all()
        new_article.categories = selected_categories
        new_article.source = request.form["source"]
        db.session.add(new_article)
        db.session.commit()

        flash("Article published successfully.")
        return redirect(url_for("home"))

    return render_template(
        "publish.html",
        categories=categories,
        countries=countries,
        article_types=article_types,
    )


# Article route
@app.route("/article/<int:article_id>")
def article(article_id):
    article = Article.query.get_or_404(article_id)
    content_html = markdown.markdown(article.content)
    return render_template("article.html", article=article, content_html=content_html)


@app.route("/edit/<int:article_id>", methods=["GET", "POST"])
@login_required
def edit_article(article_id):
    article = Article.query.get_or_404(article_id)
    countries = [country.name for country in pycountry.countries]
    article_types = ["Hack", "Leak", "News", "Opinion", "Other"]

    # Check if the current user is the author or an admin
    if not (current_user.username == article.author or current_user.is_admin):
        flash("You do not have permission to edit this article.")
        return redirect(url_for("home"))

    if request.method == "POST":
        article.title = request.form["title"]
        article.content = request.form["content"]
        article_countries = request.form.getlist(
            "countries"
        )  # Get list of selected countries
        article.country = ", ".join(article_countries)  # Join countries into a string
        article.article_type = request.form["type"]
        article.download_link = request.form["download_link"]
        db.session.commit()
        flash("Article updated successfully.")
        return redirect(url_for("article", article_id=article_id))
    else:
        selected_countries = article.country.split(", ") if article.country else []

    return render_template(
        "edit_article.html",
        article=article,
        countries=countries,
        selected_countries=selected_countries,
        article_types=article_types,
    )


@app.route("/source/<source>")
def articles_by_source(source):
    articles = Article.query.filter_by(source=source).all()
    return render_template("source_articles.html", articles=articles, source=source)


@app.route("/delete_article/<int:article_id>", methods=["POST"])
@login_required
def delete_article(article_id):
    article = Article.query.get_or_404(article_id)

    # Check if the current user is the author or an admin
    if not (current_user.username == article.author or current_user.is_admin):
        flash("You do not have permission to delete this article.")
        return redirect(url_for("home"))

    db.session.delete(article)
    db.session.commit()
    flash("Article deleted successfully.")
    return redirect(url_for("home"))


# Error handler
@app.errorhandler(Exception)
def handle_exception(e):
    app.logger.error("An error occurred: %s", e)
    return "An internal error occurred", 500


# Initialize logging
if not app.debug:
    file_handler = RotatingFileHandler(
        "app.log", maxBytes=1024 * 1024 * 100, backupCount=20
    )
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]"
        )
    )
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO)


# Database initialization function
def initialize_database():
    with app.app_context():
        db.create_all()


# Call the database initialization function
initialize_database()

if __name__ == "__main__":
    initialize_database()
    app.run(debug=True, host="0.0.0.0", port=5000)
