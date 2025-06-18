document.addEventListener('DOMContentLoaded', () => {
    const loginForm = document.getElementById('adminLoginForm');
    const errorMessageElement = document.getElementById('error-message');
    const API_BASE_URL = 'http://14.103.133.136:5000';

    if (loginForm) {
        loginForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            errorMessageElement.textContent = ''; // 清除之前的错误信息

            const username = loginForm.username.value;
            const password = loginForm.password.value;

            if (!username || !password) {
                errorMessageElement.textContent = '用户名和密码不能为空';
                return;
            }

            try {
                const response = await fetch(`${API_BASE_URL}/admin/login`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ username, password }),
                });

                const data = await response.json();

                if (response.ok && data.token) {
                    localStorage.setItem('adminToken', data.token);
                    // 登录成功后跳转到仪表盘页面
                    window.location.href = 'dashboard.html'; 
                } else {
                    errorMessageElement.textContent = data.message || '登录失败，请检查您的凭据。';
                }
            } catch (error) {
                console.error('登录请求失败:', error);
                errorMessageElement.textContent = '登录请求失败，请稍后重试。';
            }
        });
    }
});
