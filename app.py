from flask import Flask, render_template, request, redirect, url_for, flash, session
import numpy as np
import cvxpy as cp
import pyodbc

app = Flask(__name__)
app.secret_key = "your_secret_key"

#-------------------------------------------------------------Connection to SQL SERVER-------------------------------------------------------

# Configuration de la base de données
DB_CONFIG = {
    'SERVER': 'your_server_name',
    'DATABASE': 'your_database_name',
    'USERNAME': 'your_username',
    'PASSWORD': 'your_password'
}


def get_db_connection():
    """Établit et retourne une connexion à la base de données"""
    conn_str = (
        f'DRIVER={{SQL Server}};'
        f'SERVER={DB_CONFIG["SERVER"]};'
        f'DATABASE={DB_CONFIG["DATABASE"]};'
        f'UID={DB_CONFIG["USERNAME"]};'
        f'PWD={DB_CONFIG["PASSWORD"]};'
    )
    try:
        conn = pyodbc.connect(conn_str)
        return conn
    except pyodbc.Error as e:
        print(f"Database connection error: {e}")
        return None
#-------------------------------------------------------------------------------------------------------------------------------------------

# Variables globales
budget = {"income": 0, "expenses": 0, "available": 0}
objectives = []

@app.route("/")
def home():

    # Test de connexion à la base de données
    conn = get_db_connection()
    if conn:
        conn.close()
        print("Database connection successful.")
    else:
        print("Database connection failed.")
    
    # Vérifier si c'est une nouvelle session
    if 'initialized' not in session:
        # Si c'est une nouvelle session, nettoyer les données
        session.clear()
        session['initialized'] = True
    return render_template("budget.html", 
                         budget=budget,
                         user_info=session.get('user_info', {}))

@app.route("/set_budget", methods=["POST"])
def set_budget():
    # Sauvegarder les informations personnelles dans la session
    session['user_info'] = {
        "firstName": request.form.get("firstName"),
        "lastName": request.form.get("lastName"),
        "age": int(request.form.get("age"))
    }
    
    income = int(request.form.get("income"))
    expenses = int(request.form.get("expenses"))
    
    # Vérification si les dépenses sont supérieures aux revenus
    if expenses > income:
        flash("Impossible budget: your monthly expenses exceed your income. Please adjust your amounts.", "error")
        return redirect(url_for("home"))
    
    budget["income"] = income
    budget["expenses"] = expenses
    remaining = income - expenses
    budget["available"] = int(remaining * 0.9)
    
    return redirect(url_for("objectives_page"))

@app.route("/objectives")
def objectives_page():
    return render_template("objectives.html", objectives = objectives, budget = budget)

@app.route("/add_objective", methods=["POST"])
def add_objective():
    name = request.form.get("objectiveName")
    duration = int(request.form.get("duration"))
    amount = int(request.form.get("amount"))
    objectives.append({"name": name, "duration": duration, "amount": amount})
    return redirect(url_for("objectives_page"))

@app.route("/delete_objective", methods=["POST"])
def delete_objective():
    name_to_delete = request.form.get("objectiveName")
    global objectives
    objectives = [obj for obj in objectives if obj["name"] != name_to_delete]
    return redirect(url_for("objectives_page"))

@app.route("/optimization_results", methods=["POST"])
def optimization_results():
    if not objectives:
        flash("No goals added. Please add at least one goal to perform optimization.", "error")
        return redirect(url_for("objectives_page"))

    if budget["available"] <= 0:
        flash("Your available budget is insufficient to perform optimization. Check your income and expenses.", "error")
        return redirect(url_for("objectives_page"))

    # Vérification de la faisabilité des objectifs
    final_remaining_amount = budget["available"]
    lst_details = [[obj["duration"], obj["amount"]] for obj in objectives]
    if_infeasible = [np.ceil(element[1] / element[0]) for element in lst_details]
    lst_check = [final_remaining_amount >= element for element in if_infeasible]

    infeasible_report = []
    decreasing = np.ceil(abs(final_remaining_amount - np.array(if_infeasible)))
    pushing_month = [np.round(np.ceil((element[1] / final_remaining_amount)), 2) for element in lst_details]

    for i, feasible in enumerate(lst_check):
        if not feasible:
            name = objectives[i]["name"]
            advice = (
                f"The goal '{name}' is infeasible.<br>"
                f"You must either:<br>"
                f"- Reduce the total goal amount by {int(decreasing[i]) * lst_details[i][0]} ₪ "
                f"({((int(decreasing[i]) * lst_details[i][0]) / lst_details[i][1]) * 100:.2f}% of the initial amount).<br>"
                f"- Push the goal duration to {int(pushing_month[i])} month (instead of {lst_details[i][0]} month)."
            )
            infeasible_report.append(advice)

    if infeasible_report:
        flash("Unable to optimize the following objectives:<br>" + "<br>".join(infeasible_report), "error")
        return redirect(url_for("objectives_page"))

    # Résolution de l'optimisation si tous les objectifs sont réalisables
    maximum_month = max([detail[0] for detail in lst_details])
    total_objectifs = sum([detail[1] for detail in lst_details])
    x = cp.Variable(maximum_month, nonneg=True)

    constraints = []
    for element in lst_details:
        month_limit, amount = element
        constraints.append(cp.sum(x[:month_limit]) >= amount)
    constraints.append(x <= final_remaining_amount)
    constraints.append(cp.sum(x) == total_objectifs)

    problem = cp.Problem(cp.Minimize(cp.sum(x)), constraints)
    problem.solve()

    if problem.status == "optimal":
        results = [{"month": i + 1, "saving": round(val, 2)} for i, val in enumerate(x.value)]
        total_saved = round(sum(x.value), 2)
        return render_template("results.html", results=results, total_saved=total_saved)
    else:
        flash("Optimization failed. Please check your data.", "error")
        return redirect(url_for("objectives_page"))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)