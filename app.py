from flask import Flask, render_template, request, redirect, url_for 
import sqlite3
import os
import pandas as pd
from datetime import datetime
import json
import re
app = Flask(__name__)
DATABASE = "inventory.db"

@app.context_processor
def inject_datetime():
    return {'datetime': datetime}

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    # Enable foreign key constraints
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    if not os.path.exists('inventory.db'):
        conn = get_db_connection()
        c = conn.cursor()
        
        # Create items table (metadata only)
        c.execute('''CREATE TABLE IF NOT EXISTS items
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      name TEXT UNIQUE,
                      item_type TEXT,
                      item_unit TEXT,
                      minimum_inventory REAL,
                      current_inventory REAL check(current_inventory >= 0) default 0,
                      init_inventory_pm REAL,
                      updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      custom_fields TEXT)''')
        conn.commit()
        conn.close()

@app.route('/update_min_inventory/<int:item_id>', methods=['POST'])
def update_min_inventory(item_id):
    conn = get_db_connection()
    try:
        new_min_inv = request.form['new_min_inventory']
        c = conn.cursor()
        c.execute('UPDATE items SET minimum_inventory = ? WHERE id = ?', 
                 (new_min_inv, item_id))
        conn.commit()
        return redirect(url_for('item_form', item_id=item_id))
    except Exception as e:
        conn.rollback()
        return f"Error updating minimum inventory: {e}", 500
    finally:
        conn.close()

#Deletes the chosen item table and removes relevent entries from the items table
@app.route('/delete_item/<int:item_id>', methods=['POST'])
def delete_item(item_id):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        
        # 1. Get item name to determine table name
        c.execute('SELECT name FROM items WHERE id = ?', (item_id,))
        item = c.fetchone()
        
        if not item:
            return "Item not found", 404
            
        item_name = item[0]
        table_name = f"item_{normalize_names(item_name)}"
        
        # 2. Delete the specific item table
        c.execute(f'DROP TABLE IF EXISTS {table_name}')
        
        # 3. Delete the entry from items table
        c.execute('DELETE FROM items WHERE id = ?', (item_id,))
        
        conn.commit()
        return redirect(url_for('index'))
        
    except sqlite3.Error as e:
        conn.rollback()
        return f"Database error: {e}", 500
    except Exception as e:
        conn.rollback()
        return f"Error deleting item: {e}", 500
    finally:
        conn.close() 

@app.route('/edit_entry/<int:item_id>/<int:entry_id>', methods=['GET', 'POST'])
def edit_entry(item_id, entry_id):
    conn = get_db_connection()
    try:
        c = conn.cursor()

        # Get item details
        c.execute('SELECT name, item_type, item_unit, minimum_inventory, current_inventory, custom_fields FROM items WHERE id = ?', (item_id,))
        item = c.fetchone()
        if not item:
            return "Item not found", 404
        
        item_name, item_type, item_unit, min_inv, cur_inv, custom_fields_str = item
        custom_fields = json.loads(custom_fields_str) if custom_fields_str else {}
        table_name = f"item_{normalize_names(item_name)}"
             
        if request.method == 'POST':
            # Collect form data
            date = request.form.get('date')
            purchased = float(request.form.get('purchased', 0))
            used = float(request.form.get('used', 0))
            current_inventory = float(request.form.get('current_inventory' , 0))
            shift = request.form.get('shift', 'day')
            notes = request.form.get('notes', '')
            
            # Handle custom fields
            custom_values = {}
            for field_name, field_type in custom_fields.items():
                value = request.form.get(f'custom_{field_name}', '')
                if field_type == 'number':
                    value = float(value) if value else 0
                elif field_type == 'date' and not value:
                    value = None
                custom_values[field_name] = value
            
            # Calculate new current_inventory for this entry
            c.execute(f'SELECT current_inventory FROM {table_name} WHERE id < ? ORDER BY id DESC LIMIT 1', (entry_id,))
            prev_row = c.fetchone()
            if prev_row:
                prev_inventory = prev_row[0] 
            else:
                c.execute(f'SELECT init_inventory_pm from items where id = {item_id}')
                prev_inventory = c.fetchone()[0]
            print(prev_inventory)
            current_inventory = round(prev_inventory + purchased - used , 3)
            
            # Build update data
            update_data = {
                f'purchased_{item_unit}': purchased,
                f'used_{item_unit}': used,
                'date': date,
                'shift': shift,
                'notes': notes,
                'current_inventory': current_inventory
            }
            update_data.update(custom_values)
            
            # Build dynamic UPDATE query
            set_clause = ', '.join([f'"{k}" = ?' for k in update_data.keys()])
            values = list(update_data.values()) + [entry_id]
            c.execute(f'UPDATE {table_name} SET {set_clause} WHERE id = ?', values)
            
            # Get total entries and max ID
            c.execute(f'SELECT COUNT(*), MAX(id) FROM {table_name}')
            total_entries, max_entry_id = c.fetchone()
            
            if entry_id == max_entry_id:
                # Case 1: Last entry
                c.execute('UPDATE items SET current_inventory = ? WHERE id = ?', (current_inventory, item_id))
            else:
                # Case 2: First or middle entry
                c.execute(f'SELECT id, purchased_{item_unit}, used_{item_unit} FROM {table_name} WHERE id > ? ORDER BY id ASC', (entry_id,))
                subsequent_rows = c.fetchall()
                
                prev_inventory = current_inventory
                for row in subsequent_rows:
                    row_id, row_purchased, row_used = row
                    new_inventory = round(prev_inventory + (row_purchased or 0) - (row_used or 0) , 3)
                    c.execute(f'UPDATE {table_name} SET current_inventory = ? WHERE id = ?', (new_inventory, row_id))
                    prev_inventory = new_inventory
                
                # Update items table with the latest current_inventory
                c.execute(f'SELECT current_inventory FROM {table_name} ORDER BY id DESC LIMIT 1')
                latest_inventory = c.fetchone()[0]
                c.execute('UPDATE items SET current_inventory = ? WHERE id = ?', (latest_inventory, item_id))
                cur_inv = latest_inventory
            
            conn.commit()
            # After successful update, fetch all entries again
            c.execute(f"SELECT * FROM {table_name} ORDER BY id ASC")
            columns = [description[0] for description in c.description]
            entries = [dict(zip(columns, row)) for row in c.fetchall()]
            
            return render_template('item_form.html',
                                item_id=item_id,
                                item_name=item_name,
                                item_type=item_type,
                                item_unit=item_unit,
                                min_inv=min_inv,
                                cur_inv=cur_inv,
                                custom_fields=custom_fields,
                                entries=entries,
                                current_date=datetime.now().strftime('%Y-%m-%d'),
                                message="Entry updated successfully")
        
        # GET request - fetch existing data
        c.execute(f'SELECT * FROM {table_name} WHERE id = ?', (entry_id,))
        columns = [col[0] for col in c.description]
        entry_data = dict(zip(columns, c.fetchone()))
        
        return render_template('edit_entry.html',
                            item_id=item_id,
                            item_name=item_name,
                            item_unit=item_unit,
                            entry=entry_data,
                            custom_fields=custom_fields,
                            current_date=datetime.now().strftime('%Y-%m-%d'))
        
    except sqlite3.Error as e:
        conn.rollback()
        return f"Error editing entry: {e}", 500
    finally:
        conn.close()
               

@app.route('/delete_entry/<int:item_id>/<int:entry_id>', methods=['POST'])
def delete_entry(item_id, entry_id):
    conn = get_db_connection()
    try:
        # Get item name to determine table name
        c = conn.cursor()
        c.execute('SELECT name FROM items WHERE id = ?', (item_id,))
        item_name = c.fetchone()[0]
        table_name = f"item_{normalize_names(item_name)}"
        # c.execute (f'UPDATE ITEMS SET current_inventory = ? WHERE id = ?',)
        
        # Delete the entry
        c.execute(f'DELETE FROM {table_name} WHERE id = ?', (entry_id,))
        
        conn.commit()
        return redirect(url_for('item_form', item_id=item_id))
    except Exception as e:
        conn.rollback()
        return f"Error deleting entry: {e}", 500
    finally:
        conn.close()        


init_db()

@app.route('/')
def index():
    conn = get_db_connection()
    c = conn.cursor()

    # Get search term from query parameter
    search_term = request.args.get('search', '').lower()
    # Base query
    query = 'SELECT id, name, minimum_inventory, current_inventory FROM items'
    
    # Add search filter if term exists
    if search_term:
        query += ' WHERE LOWER(name) LIKE ?'
        c.execute(query, (f'%{search_term}%',))
    else:
        c.execute(query)
    
    items = c.fetchall()
    
    # Get low inventory count
    c.execute('SELECT COUNT(*) FROM items WHERE minimum_inventory >= current_inventory')
    no_of_low_inv_item = c.fetchone()
    
    conn.close()
    return render_template('index.html', items=items , no_of_low_inv_item = no_of_low_inv_item, search_term=search_term)

@app.route('/low_inventory_list' , methods = ['GET'])
def low_inventory_list():
    conn = get_db_connection()
    try:
        c = conn.cursor()
        quary = f'select count(*) from items where minimum_inventory >= current_inventory'
        c.execute(quary)
        no_of_low_inv_item = c.fetchone()
        quary = f'select id , name from items where minimum_inventory >= current_inventory'
        c.execute(quary)
        items = c.fetchall()
    except Exception as e:
        conn.rollback()
        return f"Error deleting entry: {e}", 500
    finally:
        conn.close()        

    return render_template('low_inventory_list.html' , items = items , no_of_low_inv_item = no_of_low_inv_item)

def normalize_names(names: str) -> str:
    

   # output: bearing_1_dash_5_inch   input: bearing 1-5 inch

    # Mapping of special characters to their encoded versions
    char_map = {
            '.': '_dot_',
            '/': '_slash_',
            '*': '_star_',
            '-': '_dash_',      # Space becomes regular underscore
    }
    print(names  + "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")    
    # First convert all special characters
    for char, replacement in char_map.items():
        names = names.replace(char, replacement)
        
        # Then ensure it starts with a letter
    if names and names[0].isdigit():
        names = 'n' + names
        
    names = names.lower()
    # Replace all non-alphanumeric characters with underscore
       
    return re.sub(r'[^A-Za-z0-9]', '_', names)

#def no_of_low_inv_item():

def create_item_table(c,item_name, item_unit ,custom_fields):
   # conn = sqlite3.connect('inventory.db')
  #  c = conn.cursor()
    
    # Create a safe table name (replace spaces with underscores)
    table_name = f"item_{normalize_names(item_name)}"
    
    # Basic columns for all items
    columns = [
        "id INTEGER PRIMARY KEY AUTOINCREMENT",
        "item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE",
        "purchased_"+ item_unit  +" REAL",
        "used_"+ item_unit  +" REAL",
        "date DATE",
        "current_inventory REAL CHECK(current_inventory >= 0) default 0",
        "shift TEXT",
        "notes TEXT"
    ]
    
    # Add custom fields as columns
    for field_name, field_type in custom_fields.items():
        sql_type = "TEXT"
        if field_type == "number":
            sql_type = "REAL"
        elif field_type == "date":
            sql_type = "TEXT"
        columns.append(f"{normalize_names(field_name)} {sql_type}")
    
    # Create the table
    create_sql = f"CREATE TABLE IF NOT EXISTS {table_name} ({', '.join(columns)})"
    c.execute(create_sql)
    # Add index for better performance
    c.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_item_id ON {table_name}(item_id)")
   # print(create_sql)
  
   # conn.commit()
   # conn.close()
    return table_name

@app.route('/add_item', methods=['GET', 'POST'])
def add_item():
    if request.method == 'POST':
        name = request.form['name']
        item_type = request.form['item_type']
        item_unit = request.form['item_unit']
        minimum_inventory = request.form.get('minimum_inventory', 0)
        current_inventory = request.form.get('current_inventory',0)  
        init_inventory_pm = current_inventory
        # Handle custom fields
        custom_fields = {}
        for key in request.form:
            if key.startswith('custom_field_name_'):
                index = key.split('_')[-1]
                field_name = normalize_names(request.form[key])
                print(field_name)
                field_type = request.form.get(f'custom_field_type_{index}', 'text')
                if field_name:
                    custom_fields[field_name] = field_type
        
        conn = get_db_connection()
        c = conn.cursor()
        
        try:
            # Save item metadata
            c.execute('INSERT INTO items (name, item_type, item_unit, minimum_inventory,current_inventory,init_inventory_pm,custom_fields) VALUES (?,?, ?, ?, ? ,?, ?)',
                     (name, item_type,item_unit, minimum_inventory, current_inventory,json.dumps(custom_fields)))
            create_item_table(c,name, item_unit, custom_fields)
            conn.commit()
            return redirect(url_for('index'))
        except sqlite3.IntegrityError:
            return "Item with this name already exists", 400
        finally:
            conn.close()
           # create_item_table(name, item_unit, custom_fields)
    return render_template('add_item.html')


@app.route('/add_column/<int:item_id>', methods=['GET', 'POST'])
def add_column(item_id):
    conn = get_db_connection()
    try:
        if request.method == 'POST':
            column_name = normalize_names(request.form['column_name'])
            column_type = request.form['column_type']
            
            # Get item details
            c = conn.cursor()
            c.execute('SELECT name FROM items WHERE id = ?', (item_id,))
            item_name = c.fetchone()[0]
            table_name = f"item_{normalize_names(item_name)}"
            
            # Add the new column
            sql_type = {
                'text': 'TEXT',
                'number': 'REAL',
                'date': 'TEXT'
            }.get(column_type, 'TEXT')
            
            c.execute(f'ALTER TABLE {table_name} ADD COLUMN "{column_name}" {sql_type}')
            
            # Update custom_fields in items table
            c.execute('SELECT custom_fields FROM items WHERE id = ?', (item_id,))
            custom_fields = json.loads(c.fetchone()[0] or '{}')
            custom_fields[column_name] = column_type
            c.execute('UPDATE items SET custom_fields = ? WHERE id = ?', 
                     (json.dumps(custom_fields), item_id))
            
            conn.commit()
            return redirect(url_for('item_form', item_id=item_id))
        
        return render_template('add_column.html', item_id=item_id)
        
    except sqlite3.Error as e:
        conn.rollback()
        return f"Database error: {e}", 500
    finally:
        conn.close()


#DELETES SPECIFIC CUSTOM COLUMNS FROM THE CUSTOM ITEM TABLES
@app.route('/delete_column/<int:item_id>', methods=['GET', 'POST'])
def delete_column(item_id):
    conn = get_db_connection()
    try:
         # Get item details
        c = conn.cursor()
        if request.method == 'POST':
            column_name = request.form['column_name']
            
            # Verify it's a custom column (not core columns)
            core_columns = {'date', 'shift', 'notes', 'purchased', 'used', 'current_inventory'}
            if column_name in core_columns:
                return "Cannot delete core columns", 400
            
            c.execute('SELECT name, custom_fields FROM items WHERE id = ?', (item_id,))
            item_name, custom_fields_json = c.fetchone()
            table_name = f"item_{normalize_names(item_name)}"
            custom_fields = json.loads(custom_fields_json or '{}')
            
            # Modern SQLite column deletion
            c.execute(f'ALTER TABLE {table_name} DROP COLUMN "{column_name}"')
            
            # Update custom_fields metadata
            custom_fields.pop(column_name, None)
            c.execute('UPDATE items SET custom_fields = ? WHERE id = ?', 
                     (json.dumps(custom_fields), item_id))
            
            conn.commit()
         #   flash(f"Column '{column_name}' deleted successfully", "success")
            #return redirect(url_for('item_form', item_id=item_id, message=f"Column '{column_name}' deleted successfully", message_type="success"))
            return """
                        <script>
                            alert("Column deleted successfully");
                            window.location.href = '{}';
                        </script>
                        """.format(url_for('item_form', item_id=item_id))
          #  return redirect(url_for('item_form', item_id=item_id))
        
        # GET request - show form
        c.execute('SELECT name, custom_fields FROM items WHERE id = ?', (item_id,))
        item_name, custom_fields_json = c.fetchone()
        custom_fields = json.loads(custom_fields_json or '{}')
        
        return render_template('delete_column.html',
                            item_id=item_id,
                            item_name=item_name,
                            custom_fields=custom_fields)
        
    except sqlite3.Error as e:
        conn.rollback()
       # flash(f"Error deleting column: {e}", "error")
        #return redirect(url_for('item_form', item_id=item_id, message=f"Error deleting column: {e}", message_type="error"))
        return """
                    <script>
                        alert("Error deleting Column");
                        window.location.href = '{}';
                    </script>
                    """.format(url_for('item_form', item_id=item_id))
       # return redirect(url_for('item_form', item_id=item_id))
    finally:
        conn.close()

@app.route('/item/<int:item_id>', methods=['GET', 'POST'])
def item_form(item_id):
    conn = get_db_connection()
    c = conn.cursor()
    
    # Get item details
    c.execute('SELECT name, item_type,item_unit, minimum_inventory,current_inventory, custom_fields FROM items WHERE id = ?', (item_id,))
    item = c.fetchone()
    
    if not item:
        return "Item not found", 404
    
    item_name, item_type, item_unit ,min_inv,cur_inv, custom_fields_str = item
    custom_fields = json.loads(custom_fields_str) if custom_fields_str else {}
    table_name = f"item_{normalize_names(item_name)}"
    
    if request.method == 'POST':
        date = request.form.get('date', datetime.now().strftime('%Y-%m-%d'))
        purchased = request.form.get('purchased' , 0)
        used = request.form.get('used' , 0)
        shift = request.form.get('shift', 'day')
        notes = request.form.get('notes', '')
       # print(cur_inv , purchased , used ,  '!!!!!!')
        current_inventory = round((cur_inv + float(purchased)) - float(used) , 3) 
        # Prepare columns and values
        columns = ['item_id','date' , 'purchased_'+item_unit , 'used_'+item_unit, 'current_inventory' , 'shift', 'notes']
        values = [item_id ,date , purchased ,used , current_inventory , shift, notes]
        
        # Add custom fields
        for field_name in custom_fields:
            columns.append(field_name)
            values.append(request.form.get(f'custom_{field_name}', ''))
        
        # Insert into item's dedicated table
        placeholders = ', '.join(['?'] * len(values))
        insert_sql = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"
       # print(insert_sql)
        c.execute(insert_sql, values)
        print("Values added successfully")
        update_cur_inv_items = "UPDATE items SET current_inventory = ? WHERE id = ?"
        c.execute(update_cur_inv_items, (current_inventory, item_id))
       
        print("updated current inventory in items table")
        conn.commit()
        return redirect(url_for('item_form', item_id=item_id))
    
#     # Get all entries for this item
#     c.execute(f"SELECT * FROM {table_name} ORDER BY id ASC")
#     columns = [description[0] for description in c.description]
#     entries = [dict(zip(columns, row)) for row in c.fetchall()]
#    # print(entries)
#     conn.close()

    # Get filter parameters
    month = request.args.get('month')
    year = request.args.get('year')
    
    # Base query for entries
    query = f"SELECT * FROM {table_name}"
    params = []

    # # Add this debug code to your item_form route before the month/year queries temporarily!!!!!!!!!!!!!!!!!!
    # c.execute(f"SELECT date FROM {table_name} LIMIT 1")
    # sample_date = c.fetchone()[0]
    # print(f"Sample date from DB: {sample_date}")  # Should output like "2023-06-15"
    
    # Apply filters if provided
    if month or year:
        query += " WHERE "
        conditions = []
        if month:
            conditions.append("strftime('%m', date) = ?")
            params.append(month.zfill(2))  # Ensure two-digit month
        if year:
            conditions.append("strftime('%Y', date) = ?")
            params.append(year)
        query += " AND ".join(conditions)
    
    query += " ORDER BY id ASC limit 10"
    
    # Get entries
    c.execute(query, params)
   # columns = [description[0] for description in c.description]
   # entries = [dict(zip(columns, row)) for row in c.fetchall()]
    
    # Get available years and months for filter dropdowns
    c.execute(f"SELECT DISTINCT strftime('%Y', date) AS year FROM {table_name} ORDER BY year")
    available_years = [row[0] for row in c.fetchall()]
    
    months_map = {
        '01': 'January', '02': 'February', '03': 'March',
        '04': 'April', '05': 'May', '06': 'June',
        '07': 'July', '08': 'August', '09': 'September',
        '10': 'October', '11': 'November', '12': 'December'
        }

    c.execute(f"SELECT DISTINCT strftime('%m-%Y', date) AS month_year FROM {table_name} ORDER BY month_year DESC")
    available_months = [ (row[0], months_map.get(row[0][:2], 'Unknown')) for row in c.fetchall()]
    print(available_months)

    #get search parameter
    search_res = request.args.get('date_search')
    print(search_res , "!!!!!!!!!!!!here")
    # Modify your entries query to include date filter
    query = f"SELECT * FROM {table_name} "
    params = []
    if search_res:
        print(search_res)
        query += "where date = ?"
        params.append(search_res)
    
    query += " ORDER BY id ASC limit 10"
    print(query)
    print(params)
    c.execute(query , params)
    columns = [description[0] for description in c.description]
    entries = [dict(zip(columns, row)) for row in c.fetchall()]
    

    
    conn.close()
    
    return render_template('item_form.html', 
                         item_id=item_id,
                         item_name=item_name,
                         item_type=item_type,
                         item_unit = item_unit,
                         min_inv=min_inv,
                         cur_inv = cur_inv,
                         custom_fields=custom_fields,
                         entries=entries,
                         current_date=datetime.now().strftime('%Y-%m-%d'),
                         available_years=available_years,
                         available_months=available_months,
                         current_year=year,
                         current_month=month)


@app.route('/download_excel/<int:item_id>')
def generate_excel(item_id):
    """Generate Excel file and return file path"""
    try:
        conn = get_db_connection()
        
        # Get item name
        item_name = pd.read_sql('SELECT name FROM items WHERE id = ?', 
                               conn, params=(item_id,)).iloc[0]['name']
        
        # Get table name
        table_name = f"item_{item_name.lower().replace(' ', '_')}"
        
        # Check if table exists
        if not pd.read_sql(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'", conn).empty:
            # Read data
            df = pd.read_sql(f'SELECT * FROM {table_name}', conn)
            
            # Create filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"static/exports/{item_name}_inventory_{timestamp}.xlsx"
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            
            # Save to Excel
            df.to_excel(filename, index=False)
            return filename
        return None
        
    except Exception as e:
        print(f"Error generating Excel: {e}")
        return None
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    # Ensure the database is initialized before running
    if not os.path.exists(DATABASE):
        init_db()
    app.run(debug=True)
    print("This is for testing how githuib works")
   # app.run(debug=True)