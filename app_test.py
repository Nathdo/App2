from flask import Flask, render_template, request, redirect, url_for, flash, session
import numpy as np
import cvxpy as cp
import psycopg2
import secrets

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)  

# -------------------------------------------------------------
# Connexion à PostgreSQL
# -------------------------------------------------------------
DB_CONFIG = {
    'dbname': 'save_go',
    'user': 'postgres',
    'password': 'Nathan99',  # Remplace par ton mot de passe PostgreSQL
    'host': 'localhost',
    'port': '5432'
}

def get_db_connection():
    """Établit et retourne une connexion à PostgreSQL"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        return None

# -------------------------------------------------------------
# Routes Flask
# -------------------------------------------------------------
@app.route("/")
def home():
    # Réinitialiser la session pour éviter d'afficher les anciens objectifs
    session.clear()
    session['initialized'] = True
    session['budget'] = {"income": 0, "expenses": 0, "available": 0}
    session['objectives'] = []
    session['user_info'] = {}
    session['user_id'] = None  # Aucun utilisateur connecté au départ

    return render_template("budget.html", 
                           budget=session['budget'],
                           user_info=session['user_info'])

@app.route("/set_budget", methods=["POST"])
def set_budget():
    session['user_info'] = {
        "firstName": request.form.get("firstName"),
        "lastName": request.form.get("lastName")
    }

    income = int(request.form.get("income"))
    expenses = int(request.form.get("expenses"))

    if expenses > income:
        flash("Impossible budget: your monthly expenses exceed your income. Please adjust your amounts.", "error")
        return redirect(url_for("home"))

    session['budget'] = {
        "income": income,
        "expenses": expenses,
        "available": int((income - expenses) * 0.9)
    }

    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO users (firstName, lastName, income, expenses)
                VALUES (%s, %s, %s, %s) RETURNING userID;
            """, (session['user_info']["firstName"], session['user_info']["lastName"], income, expenses))
            session['user_id'] = cur.fetchone()[0]  # Sauvegarde userID dans la session
            conn.commit()
            cur.close()
            flash(f"User {session['user_info']['firstName']} {session['user_info']['lastName']} registered.", "success")
        except Exception as e:
            flash("Database error: " + str(e), "error")
        finally:
            conn.close()

    return redirect(url_for("objectives_page"))

@app.route("/objectives")
def objectives_page():
    if not session.get('user_id'):
        session['objectives'] = []  # Aucun objectif pour un utilisateur non connecté
        return render_template("objectives.html", objectives=[], budget=session.get('budget', {}))

    conn = get_db_connection()
    objectives = []

    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT planName, sumOfMonths, sumOfMoney 
                FROM plans 
                WHERE planID IN (
                    SELECT planID FROM userplans WHERE userID = %s
                );
            """, (session['user_id'],))
            rows = cur.fetchall()
            for row in rows:
                objectives.append({
                    "name": row[0],
                    "duration": row[1],
                    "amount": row[2]
                })
            cur.close()
        except Exception as e:
            flash("Database error: " + str(e), "error")
        finally:
            conn.close()

    return render_template("objectives.html", 
                           objectives=objectives, 
                           budget=session.get('budget', {}))

@app.route("/add_objective", methods=["POST"])
def add_objective():
    if not session.get('user_id'):
        flash("Please register a budget first.", "error")
        return redirect(url_for("home"))

    duration = int(request.form.get("duration"))

    if duration > 12:
        flash("The duration of a goal cannot exceed 12 months. Please adjust your duration.", "error")
        return redirect(url_for("objectives_page"))

    objective = {
        "name": request.form.get("objectiveName"),
        "duration": int(request.form.get("duration")),
        "amount": int(request.form.get("amount"))
    }

    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO plans (planName, sumOfMonths, sumOfMoney)
                VALUES (%s, %s, %s) RETURNING planID;
            """, (objective["name"], objective["duration"], objective["amount"]))
            plan_id = cur.fetchone()[0]

            # Associer l'objectif à l'utilisateur
            cur.execute("""
                INSERT INTO userplans (userID, planID)
                VALUES (%s, %s);
            """, (session['user_id'], plan_id))

            conn.commit()
            cur.close()
            flash(f"Objective '{objective['name']}' added.", "success")
        except Exception as e:
            flash("Database error: " + str(e), "error")
        finally:
            conn.close()

    return redirect(url_for("objectives_page"))

@app.route("/delete_objective", methods=["POST"])
def delete_objective():
    if not session.get('user_id'):
        flash("Please register a budget first.", "error")
        return redirect(url_for("home"))

    name_to_delete = request.form.get("objectiveName")

    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            
            # Récupérer planID correspondant au nom
            cur.execute("SELECT planID FROM plans WHERE planName = %s;", (name_to_delete,))
            plan_id = cur.fetchone()
            
            if plan_id:
                plan_id = plan_id[0]
                # Supprimer l'association avec l'utilisateur
                cur.execute("DELETE FROM userplans WHERE userID = %s AND planID = %s;", (session['user_id'], plan_id))
                # Supprimer le plan si plus personne ne l'utilise
                cur.execute("DELETE FROM plans WHERE planID = %s;", (plan_id,))
                conn.commit()
                flash(f"Objective '{name_to_delete}' deleted.", "success")

            cur.close()
        except Exception as e:
            flash("Database error: " + str(e), "error")
        finally:
            conn.close()

    return redirect(url_for("objectives_page"))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8000)
