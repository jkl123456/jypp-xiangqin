document.addEventListener('DOMContentLoaded', () => {
    const adminToken = localStorage.getItem('adminToken');
    if (!adminToken) {
        window.location.href = 'login.html';
        return;
    }

    const usersTableBody = document.querySelector('#usersTable tbody');
    const logoutButton = document.getElementById('logoutButton');

    // 编辑模态框相关元素
    const editUserModal = document.getElementById('editUserModal');
    const closeEditModalBtn = document.getElementById('closeEditModal');
    const editUserForm = document.getElementById('editUserForm');
    const editUserIdField = document.getElementById('editUserId');

    const API_BASE_URL = 'http://14.103.133.136:5000';
    
    let currentPage = 1;
    let totalPages = 1;
    const usersPerPage = 15; // 和后端API的per_page默认值保持一致

    const prevPageButton = document.getElementById('prevPageButton');
    const nextPageButton = document.getElementById('nextPageButton');
    const pageInfoSpan = document.getElementById('pageInfo');


    // 登出
    if (logoutButton) {
        logoutButton.addEventListener('click', () => {
            localStorage.removeItem('adminToken');
            window.location.href = 'login.html';
        });
    }

    // 加载用户列表
    async function fetchUsers(page = 1) {
        try {
            const response = await fetch(`${API_BASE_URL}/admin/users?page=${page}&per_page=${usersPerPage}`, {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${adminToken}`,
                    'Content-Type': 'application/json'
                }
            });

            if (response.status === 401) { // Token 无效或过期
                localStorage.removeItem('adminToken');
                window.location.href = 'login.html';
                return;
            }
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.message || `获取用户列表失败: ${response.statusText}`);
            }

            const data = await response.json();
            currentPage = data.page;
            totalPages = data.total_pages;
            renderUsers(data.users);
            renderPagination();
        } catch (error) {
            console.error('获取用户列表错误:', error);
            if (usersTableBody) usersTableBody.innerHTML = `<tr><td colspan="8" style="text-align:center;">加载用户数据失败: ${error.message}</td></tr>`;
            if (pageInfoSpan) pageInfoSpan.textContent = '加载失败';
            if (prevPageButton) prevPageButton.disabled = true;
            if (nextPageButton) nextPageButton.disabled = true;
        }
    }

    // 渲染分页控件
    function renderPagination() {
        if (pageInfoSpan) pageInfoSpan.textContent = `第 ${currentPage} / ${totalPages} 页`;
        
        if (prevPageButton) prevPageButton.disabled = currentPage <= 1;
        if (nextPageButton) nextPageButton.disabled = currentPage >= totalPages;
    }
    
    if (prevPageButton) {
        prevPageButton.addEventListener('click', () => {
            if (currentPage > 1) {
                fetchUsers(currentPage - 1);
            }
        });
    }

    if (nextPageButton) {
        nextPageButton.addEventListener('click', () => {
            if (currentPage < totalPages) {
                fetchUsers(currentPage + 1);
            }
        });
    }


    // 渲染用户列表到表格
    function renderUsers(users) {
        if (!usersTableBody) return;
        usersTableBody.innerHTML = ''; // 清空现有行

        if (!users || users.length === 0) {
            usersTableBody.innerHTML = '<tr><td colspan="8" style="text-align:center;">暂无用户数据</td></tr>';
            return;
        }

        users.forEach(user => {
            const row = usersTableBody.insertRow();
            row.insertCell().textContent = user.id;
            row.insertCell().textContent = user.email;
            row.insertCell().textContent = user.nickname || 'N/A';
            row.insertCell().textContent = user.age || 'N/A';
            row.insertCell().textContent = user.gender || 'N/A';
            row.insertCell().textContent = user.created_at ? new Date(user.created_at).toLocaleString() : 'N/A';
            row.insertCell().textContent = user.last_online ? new Date(user.last_online).toLocaleString() : 'N/A';
            
            const actionsCell = row.insertCell();
            actionsCell.classList.add('actions');

            const viewButton = document.createElement('a');
            viewButton.href = `user_details.html?id=${user.id}`;
            viewButton.textContent = '查看';
            viewButton.classList.add('view-btn', 'button');
            actionsCell.appendChild(viewButton);
            
            const editButton = document.createElement('button');
            editButton.textContent = '编辑';
            editButton.classList.add('edit-btn');
            editButton.addEventListener('click', () => openEditModal(user.id));
            actionsCell.appendChild(editButton);

            const deleteButton = document.createElement('button');
            deleteButton.textContent = '删除';
            deleteButton.classList.add('delete-btn');
            deleteButton.addEventListener('click', () => deleteUser(user.id, user.nickname || user.email));
            actionsCell.appendChild(deleteButton);
        });
    }

    // 打开编辑模态框并填充数据
    async function openEditModal(userId) {
        if (!editUserModal || !editUserForm) return;
        try {
            const response = await fetch(`${API_BASE_URL}/admin/users/${userId}`, {
                headers: { 'Authorization': `Bearer ${adminToken}` }
            });
            if (!response.ok) throw new Error('获取用户详情失败');
            const user = await response.json();

            editUserIdField.value = user.id;
            document.getElementById('editNickname').value = user.nickname || '';
            document.getElementById('editEmail').value = user.email || '';
            document.getElementById('editAge').value = user.age || '';
            document.getElementById('editGender').value = user.gender || '';
            document.getElementById('editProfession').value = user.profession || '';
            document.getElementById('editProvince').value = user.province || '';
            document.getElementById('editCity').value = user.city || '';
            document.getElementById('editInterests').value = user.interests || '';
            document.getElementById('editBio').value = user.bio || '';
            document.getElementById('editAvatar').value = user.avatar || '';
            document.getElementById('editPassword').value = ''; // 清空密码字段
            
            editUserModal.style.display = 'block';
        } catch (error) {
            console.error('打开编辑模态框失败:', error);
            alert(`加载用户信息失败: ${error.message}`);
        }
    }

    // 关闭编辑模态框
    if (closeEditModalBtn) {
        closeEditModalBtn.onclick = () => {
            if (editUserModal) editUserModal.style.display = 'none';
        }
    }
    window.onclick = (event) => {
        if (event.target == editUserModal) {
            editUserModal.style.display = 'none';
        }
    }

    // 提交编辑表单
    if (editUserForm) {
        editUserForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            const userId = editUserIdField.value;
            const updatedData = {
                nickname: document.getElementById('editNickname').value,
                email: document.getElementById('editEmail').value,
                age: document.getElementById('editAge').value ? parseInt(document.getElementById('editAge').value) : null,
                gender: document.getElementById('editGender').value,
                profession: document.getElementById('editProfession').value,
                province: document.getElementById('editProvince').value,
                city: document.getElementById('editCity').value,
                interests: document.getElementById('editInterests').value,
                bio: document.getElementById('editBio').value,
                avatar: document.getElementById('editAvatar').value,
            };
            const password = document.getElementById('editPassword').value;
            if (password) {
                updatedData.password = password;
            }

            try {
                const response = await fetch(`${API_BASE_URL}/admin/users/${userId}`, {
                    method: 'PUT',
                    headers: {
                        'Authorization': `Bearer ${adminToken}`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(updatedData)
                });
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.message || '更新用户信息失败');
                }
                alert('用户信息更新成功!');
                if (editUserModal) editUserModal.style.display = 'none';
                fetchUsers(); // 刷新列表
            } catch (error) {
                console.error('更新用户失败:', error);
                alert(`更新失败: ${error.message}`);
            }
        });
    }

    // 删除用户
    async function deleteUser(userId, userName) {
        if (!confirm(`确定要删除用户 "${userName}" (ID: ${userId}) 吗？此操作不可恢复。`)) {
            return;
        }
        try {
            const response = await fetch(`${API_BASE_URL}/admin/users/${userId}`, {
                method: 'DELETE',
                headers: {
                    'Authorization': `Bearer ${adminToken}`
                }
            });
            if (!response.ok) {
                 const errorData = await response.json();
                throw new Error(errorData.message || '删除用户失败');
            }
            alert(`用户 ${userName} 已成功删除。`);
            fetchUsers(); // 刷新列表
        } catch (error) {
            console.error('删除用户错误:', error);
            alert(`删除用户失败: ${error.message}`);
        }
    }

    // 初始加载
    fetchUsers(currentPage);
});
