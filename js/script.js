fetch('data/rates.json')
    .then(response => response.json())
    .then(data => {
        const container = document.getElementById('rates-container');
        data.forEach(item => {
            const card = document.createElement('div');
            card.className = 'col-md-4 rate-card';
            card.innerHTML = `
                <h5>${item.flag} ${item.name}</h5>
                <p>نرخ: ${item.rate} تومان</p>
                <p>تغییر: ${item.change || '0'} ${item.direction} (${item.percent}%)</p>
            `;
            container.appendChild(card);
        });
    })
    .catch(error => console.error('Error loading rates:', error));
