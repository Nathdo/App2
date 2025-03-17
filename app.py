from flask import Flask, render_template, request, redirect, url_for, flash, session
import numpy as np
import cvxpy as cp
import pyodbc
import secrets

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)  # Clé secrète aléatoire

#------------------------------------------------------------- Connection à SQL SERVER -------------------------------------------------------

DB_CONFIG = {
    'SERVER': 'LAPTOP-E9GDKQ4I\\SQLEXPRESS',
    'DATABASE': 'Maarehet_Meida',
}

def get_db_connection():
    """Établit et retourne une connexion à la base de données"""
    conn_str = (
        f'DRIVER={{SQL Server}};'
        f'SERVER={DB_CONFIG["SERVER"]};'
        f'DATABASE={DB_CONFIG["DATABASE"]};'
    )
    try:
        conn = pyodbc.connect(conn_str)
        return conn
    except pyodbc.Error as e:
        print(f"Database connection error: {e}")
        return None

#------------------------------------------------------------- Gestion des utilisateurs -------------------------------------------------------

def insert_user(first_name, last_name, income, expenses):
    """Insère un utilisateur dans la base de données et retourne son ID."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Vérifier si l'utilisateur existe déjà
            query_check = "SELECT UserID FROM Users WHERE FirstName = ? AND LastName = ?"
            cursor.execute(query_check, (first_name, last_name))
            existing_user = cursor.fetchone()
            
            if existing_user:
                return existing_user[0]
            
            # Insérer le nouvel utilisateur
            query = """
            INSERT INTO Users (FirstName, LastName, Income, Expenses) 
            OUTPUT INSERTED.UserID
            VALUES (?, ?, ?, ?)
            """
            cursor.execute(query, (first_name, last_name, income, expenses))
            user_id = cursor.fetchone()[0]
            conn.commit()
            return user_id
        except pyodbc.Error as e:
            print(f"Database insertion error: {e}")
            return None
        finally:
            conn.close()
    return None

def get_user_id(first_name, last_name):
    """Récupère l'ID de l'utilisateur."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            query = "SELECT UserID FROM Users WHERE FirstName = ? AND LastName = ?"
            cursor.execute(query, (first_name, last_name))
            result = cursor.fetchone()
            return result[0] if result else None
        except pyodbc.Error as e:
            print(f"Database query error: {e}")
            return None
        finally:
            conn.close()
    return None

@app.route("/")
def home():
    if 'initialized' not in session:
        session.clear()
        session['initialized'] = True
        session['budget'] = {"income": 0, "expenses": 0, "available": 0}
        session['objectives'] = []
        session['user_info'] = {}
        session['user_id'] = None  # Ajouter un ID utilisateur à la session

    return render_template("budget.html", 
                         budget=session['budget'],
                         user_info=session['user_info'])

@app.route("/set_budget", methods=["POST"])
def set_budget():
    first_name = request.form.get("firstName")
    last_name = request.form.get("lastName")
    income = int(request.form.get("income"))
    expenses = int(request.form.get("expenses"))

    if expenses > income:
        flash("Impossible budget: your monthly expenses exceed your income. Please adjust your amounts.", "error")
        return redirect(url_for("home"))

    # Insérer l'utilisateur et récupérer son ID
    user_id = insert_user(first_name, last_name, income, expenses)
    
    # Stocker l'ID utilisateur dans la session
    session['user_id'] = user_id
    
    session['user_info'] = {
        "firstName": first_name,
        "lastName": last_name
    }

    session['budget'] = {
        "income": income,
        "expenses": expenses,
        "available": int((income - expenses) * 0.9)
    }

    return redirect(url_for("objectives_page"))

#------------------------------------------------------------- Gestion des objectifs -------------------------------------------------------

def insert_plan(plan_name, duration, amount, user_id):
    """Insère un plan et crée l'association avec l'utilisateur."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Insérer le plan
            cursor.execute("""
                INSERT INTO Plans (PlanName, SumOfMonths, SumOfMoney) 
                OUTPUT INSERTED.PlanID
                VALUES (?, ?, ?)
            """, (plan_name, duration, amount))
            plan_id = cursor.fetchone()[0]
            
            # Créer l'association dans la table UserPlans
            cursor.execute("""
                INSERT INTO UserPlans (UserID, PlanID)
                VALUES (?, ?)
            """, (user_id, plan_id))
            
            conn.commit()
            return plan_id
        except pyodbc.Error as e:
            print(f"Database insertion error: {e}")
            conn.rollback()
        finally:
            conn.close()
    return None

@app.route("/objectives")
def objectives_page():
    # Vérifier si l'ID utilisateur est dans la session
    if 'user_id' not in session or not session['user_id']:
        # Si pas d'ID utilisateur, rediriger vers la page d'accueil
        flash("Please enter your budget information first.", "error")
        return redirect(url_for("home"))
        
    return render_template("objectives.html", 
                         objectives=session.get('objectives', []), 
                         budget=session.get('budget', {}))

@app.route("/add_objective", methods=["POST"])
def add_objective():
    # Utiliser l'ID utilisateur de la session au lieu de le rechercher
    user_id = session.get('user_id')
    
    if not user_id:
        flash("User not found. Please enter your budget first.", "error")
        return redirect(url_for("home"))

    plan_name = request.form.get("objectiveName")
    duration = int(request.form.get("duration"))
    amount = int(request.form.get("amount"))

    if duration > 12:
        flash("The duration of a goal cannot exceed 12 months.", "error")
        return redirect(url_for("objectives_page"))

    # Passer l'ID utilisateur à la fonction insert_plan
    plan_id = insert_plan(plan_name, duration, amount, user_id)
    
    if 'objectives' not in session:
        session['objectives'] = []

    session['objectives'].append({
        "name": plan_name,
        "duration": duration,
        "amount": amount
    })
    
    # S'assurer que les modifications de la session sont enregistrées
    session.modified = True

    return redirect(url_for("objectives_page"))

#------------------------------------------------------------- Sauvegarde des résultats -------------------------------------------------------

def insert_optimization_results(user_id, savings):
    """Insère les résultats de l'optimisation pour un utilisateur dans Outputs."""
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            query = """
            INSERT INTO Outputs (UserID, Month1, Month2, Month3, Month4, Month5, Month6, 
                                Month7, Month8, Month9, Month10, Month11, Month12) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            cursor.execute(query, [user_id] + savings)
            conn.commit()
            return True
        except pyodbc.Error as e:
            print(f"Database insertion error: {e}")
            return False
        finally:
            conn.close()
    return False

@app.route("/optimization_results", methods=["POST"])
def optimization_results():
    # Utiliser l'ID utilisateur de la session
    user_id = session.get('user_id')

    if not user_id:
        flash("User not found. Please enter your budget first.", "error")
        return redirect(url_for("home"))

    objectives = session.get('objectives', [])
    budget = session.get('budget', {})

    if not objectives:
        flash("No goals added. Please add at least one goal.", "error")
        return redirect(url_for("objectives_page"))

    if budget["available"] <= 0:
        flash("Your available budget is insufficient.", "error")
        return redirect(url_for("objectives_page"))

    max_months = 12
    savings = np.zeros(max_months)

    for obj in objectives:
        per_month = obj["amount"] / obj["duration"]
        for i in range(obj["duration"]):
            savings[i] += per_month

    savings = [round(x, 2) for x in savings]

    # Insérer les résultats avec l'ID utilisateur de la session
    success = insert_optimization_results(user_id, savings)
    
    if not success:
        flash("There was an error saving your results.", "error")
        return redirect(url_for("objectives_page"))

    results = [{"month": i + 1, "saving": savings[i]} for i in range(max_months)]
    total_saved = round(sum(savings), 2)

    return render_template("results.html", results=results, total_saved=total_saved)

# Route pour supprimer un objectif (pour compléter la fonctionnalité dans objectives.html)
@app.route("/delete_objective", methods=["POST"])
def delete_objective():
    objective_name = request.form.get("objectiveName")
    
    if 'objectives' in session:
        session['objectives'] = [obj for obj in session['objectives'] if obj['name'] != objective_name]
        session.modified = True
    
    return redirect(url_for("objectives_page"))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8000)