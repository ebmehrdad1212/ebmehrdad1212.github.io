<script>
        function fetchLogs() {
            fetch('/logs')
                .then(response => response.json())
                .then(data => {
                    const logsDiv = document.getElementById('logs');
                    logsDiv.innerHTML = '';
                    data.forEach(log => {
                        const p = document.createElement('p');
                        p.innerHTML = log;
                        logsDiv.appendChild(p);
                    });
                    logsDiv.scrollTop = logsDiv.scrollHeight;
                });
        }
        setInterval(fetchLogs, 5000);
        window.onload = fetchLogs;

        function startBot() {
            fetch('/start', { method: 'POST' })
                .then(response => response.json())
                .then(data => alert(data.status));
        }

        function stopBot() {
            fetch('/stop', { method: 'POST' })
                .then(response => response.json())
                .then(data => alert(data.status));
        }
    </script>