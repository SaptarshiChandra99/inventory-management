@app.route('/edit_entry/<int:item_id>/<int:entry_id>', methods=['GET', 'POST'])
def edit_entry(item_id, entry_id):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        
        # Get item details
        c.execute('SELECT name, item_unit, custom_fields FROM items WHERE id = ?', (item_id,))
        item = c.fetchone()
        if not item:
            return "Item not found", 404
        
        item_name, item_unit, custom_fields_str = item
        custom_fields = json.loads(custom_fields_str) if custom_fields_str else {}
        table_name = f"item_{normalize_names(item_name)}"
             
        if request.method == 'POST':
            # Collect form data
            date = request.form.get('date')
            purchased = int(request.form.get('purchased', 0))
            used = int(request.form.get('used', 0))
            shift = request.form.get('shift', 'day')
            notes = request.form.get('notes', '')
            
            # Handle custom fields
            custom_values = {}
            for field_name, field_type in custom_fields.items():
                value = request.form.get(f'custom_{field_name}', '')
                if field_type == 'number':
                    value = int(value) if value else 0
                elif field_type == 'date' and not value:
                    value = None
                custom_values[field_name] = value
            
            # Calculate new current_inventory for this entry
            c.execute(f'SELECT current_inventory FROM {table_name} WHERE id < ? ORDER BY id DESC LIMIT 1', (entry_id,))
            prev_row = c.fetchone()
            prev_inventory = prev_row[0] if prev_row else 0
            current_inventory = prev_inventory + purchased - used
            
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
                    new_inventory = prev_inventory + (row_purchased or 0) - (row_used or 0)
                    c.execute(f'UPDATE {table_name} SET current_inventory = ? WHERE id = ?', (new_inventory, row_id))
                    prev_inventory = new_inventory
                
                # Update items table with the latest current_inventory
                c.execute(f'SELECT current_inventory FROM {table_name} ORDER BY id DESC LIMIT 1')
                latest_inventory = c.fetchone()[0]
                c.execute('UPDATE items SET current_inventory = ? WHERE id = ?', (latest_inventory, item_id))
            
            conn.commit()
            return render_template('update_entry.html',
                                item_id=item_id,
                                item_name=item_name,
                                item_unit=item_unit,
                                custom_fields=custom_fields,
                                entry={},
                                current_date=datetime.now().strftime('%Y-%m-%d'),
                                message="Entry updated successfully",
                                message_type="success")
        
        # GET request - fetch existing data
        c.execute(f'SELECT * FROM {table_name} WHERE id = ?', (entry_id,))
        columns = [col[0] for col in c.description]
        entry_data = dict(zip(columns, c.fetchone()))
        
        return render_template('update_entry.html',
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





#******* working function ***********


@app.route('/edit_entry/<int:item_id>/<int:entry_id>', methods=['GET', 'POST'])
def edit_entry(item_id, entry_id):
    conn = get_db_connection()
    try:
        # Get item details
        c = conn.cursor()
        c.execute('SELECT name, item_unit, custom_fields FROM items WHERE id = ?', (item_id,))
        item_name, item_unit, custom_fields_str = c.fetchone()
        custom_fields = json.loads(custom_fields_str) if custom_fields_str else {}
        table_name = f"item_{normalize_names(item_name)}"

        if request.method == 'POST':
            # Handle form submission !!!! current inventory needs recalculation
            update_data = {
                'date': request.form.get('date'),
                f'purchased_{item_unit}': request.form.get('purchased'),
                f'used_{item_unit}': request.form.get('used'),
                'shift': request.form.get('shift'),
                'current_inventory': request.form.get('current_inventory'),
                'notes': request.form.get('notes')
            }

            # Add custom fields
            for field_name in custom_fields:
                update_data[field_name] = request.form.get(f'custom_{field_name}')              

            # Build dynamic UPDATE query
            set_clause = ', '.join([f"{k} = ?" for k in update_data.keys()])
            values = list(update_data.values()) + [entry_id]

            c.execute(f'''
                UPDATE {table_name} 
                SET {set_clause}
                WHERE id = ?
            ''', values)

            conn.commit()
            return redirect(url_for('item_form', item_id=item_id))

        # GET request - fetch existing data
        c.execute(f'SELECT * FROM {table_name} WHERE id = ?', (entry_id,))
        columns = [col[0] for col in c.description]
        entry_data = dict(zip(columns, c.fetchone()))

        # c.execute(f'''select count(*) from {table_name}''')
        # no_of_items = c.fetchone()[0]
        # print(no_of_items , entry_id)
        # if entry_id != no_of_items:
        #     c.execute(f'UPDATE ITEMS SET CURRENT_INVENTORY = {update_data[current_inventory]} where id = {item_id} ')
        #     conn.commit()
        # else
                
        
        return render_template('edit_entry.html',
                            item_id=item_id,
                            entry_id=entry_id,
                            item_name=item_name,
                            item_unit=item_unit,
                            entry=entry_data,
                            custom_fields=custom_fields)
    except Exception as e:
        conn.rollback()
        return f"Error editing entry: {e}", 500
    finally:
        conn.close()