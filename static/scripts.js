document.addEventListener('DOMContentLoaded', function() {
    // Toggle minimum inventory form
    window.toggleMinInvEdit = function() {
        const form = document.getElementById('minInvForm');
        const button = document.getElementById('editMinInvBtn');
        
        if (form.style.display === 'none') {
            form.style.display = 'block';
            button.style.display = 'none';
        } else {
            form.style.display = 'none';
            button.style.display = 'inline-flex';
        }
    };

    // Add custom fields
    let customFieldCounter = 1;
    const addCustomFieldBtn = document.getElementById('add-custom-field');
    if (addCustomFieldBtn) {
        addCustomFieldBtn.addEventListener('click', function() {
            const container = document.getElementById('custom-fields-container');
            const newField = document.createElement('div');
            newField.className = 'custom-field';
            newField.innerHTML = `
                <input type="text" name="custom_field_name_${customFieldCounter}" placeholder="Field Name">
                <select name="custom_field_type_${customFieldCounter}">
                    <option value="text">Text</option>
                    <option value="number">Number</option>
                    <option value="date">Date</option>
                </select>
            `;
            container.appendChild(newField);
            customFieldCounter++;
        });
    }

    // Search input clear button
    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
        const clearSearch = document.querySelector('.clear-search');
        
        function toggleClearButton() {
            if (clearSearch) {
                clearSearch.style.display = searchInput.value ? 'block' : 'none';
            }
        }

        toggleClearButton();
        searchInput.addEventListener('input', toggleClearButton);
    }

    // Calculate current inventory when purchased or used changes
    const purchasedInput = document.getElementById('purchased');
    const usedInput = document.getElementById('used');
    const currentInventoryInput = document.getElementById('current_inventory');
    
    if (purchasedInput && usedInput && currentInventoryInput) {
        function calculateCurrentInventory() {
            const purchased = parseFloat(purchasedInput.value) || 0;
            const used = parseFloat(usedInput.value) || 0;
            const current = parseFloat(currentInventoryInput.dataset.current) || 0;
            currentInventoryInput.value = (current + purchased - used).toFixed(3);
        }
        
        purchasedInput.addEventListener('input', calculateCurrentInventory);
        usedInput.addEventListener('input', calculateCurrentInventory);
    }
});