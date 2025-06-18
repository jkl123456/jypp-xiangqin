document.addEventListener('DOMContentLoaded', () => {
    const adminToken = localStorage.getItem('adminToken');
    if (!adminToken) {
        window.location.href = 'login.html';
        return;
    }

    const logoutButton = document.getElementById('logoutButton');
    if (logoutButton) {
        logoutButton.addEventListener('click', () => {
            localStorage.removeItem('adminToken');
            window.location.href = 'login.html';
        });
    }

    const API_BASE_URL = 'http://14.103.133.136:5000'; 
    const params = new URLSearchParams(window.location.search);
    const userId = params.get('id');

    if (!userId) {
        alert('未指定用户ID');
        window.location.href = 'dashboard.html';
        return;
    }
    
    document.getElementById('userDetailsTitle').textContent = `用户详情 (ID: ${userId})`;

    // Helper function to safely set text content
    const setText = (id, text) => {
        const el = document.getElementById(id);
        if (el) el.textContent = text || 'N/A';
    };
    const setSrc = (id, src) => {
        const el = document.getElementById(id);
        if (el) el.src = src || '';
         if (el && !src) el.style.display = 'none'; else if (el) el.style.display = 'inline';
    };

    // 1. 加载用户基本信息和卡片
    async function fetchUserDetails() {
        try {
            const response = await fetch(`${API_BASE_URL}/admin/users/${userId}`, {
                headers: { 'Authorization': `Bearer ${adminToken}` }
            });
            if (!response.ok) throw new Error(`获取用户详情失败: ${response.statusText}`);
            const user = await response.json();

            setText('detailUserId', user.id);
            setText('detailEmail', user.email);
            setText('detailNickname', user.nickname);
            setText('detailAge', user.age);
            setText('detailGender', user.gender);
            setText('detailProfession', user.profession);
            setText('detailProvince', user.province);
            setText('detailCity', user.city);
            setText('detailInterests', user.interests);
            setText('detailBio', user.bio);
            setSrc('detailAvatar', user.avatar);
            setText('detailCreatedAt', user.created_at ? new Date(user.created_at).toLocaleString() : 'N/A');
            setText('detailLastOnline', user.last_online ? new Date(user.last_online).toLocaleString() : 'N/A');

            // 渲染卡片
            const cardsContainer = document.getElementById('cardsContainer');
            if (cardsContainer) {
                cardsContainer.innerHTML = ''; // Clear previous cards
                if (user.cards && user.cards.length > 0) {
                    user.cards.forEach(card => {
                        const img = document.createElement('img');
                        img.src = card.image_url;
                        img.alt = `卡片 ${card.order_index + 1}`;
                        img.classList.add('card-image');
                        cardsContainer.appendChild(img);
                    });
                } else {
                    cardsContainer.textContent = '暂无卡片信息。';
                }
            }

        } catch (error) {
            console.error('加载用户基本信息失败:', error);
            alert(`加载用户基本信息失败: ${error.message}`);
            document.getElementById('basicInfoSection').innerHTML = `<p>${error.message}</p>`;
        }
    }

    // 2. 加载匹配历史
    async function fetchMatches() {
        try {
            const response = await fetch(`${API_BASE_URL}/admin/users/${userId}/matches`, {
                headers: { 'Authorization': `Bearer ${adminToken}` }
            });
            if (!response.ok) throw new Error(`获取匹配历史失败: ${response.statusText}`);
            const data = await response.json();
            const matchesTableBody = document.getElementById('matchesTableBody');
            if (matchesTableBody) {
                matchesTableBody.innerHTML = '';
                if (data.matches && data.matches.length > 0) {
                    data.matches.forEach(match => {
                        const row = matchesTableBody.insertRow();
                        row.insertCell().textContent = match.match_id;
                        row.insertCell().textContent = match.user_id1;
                        row.insertCell().textContent = match.user1_nickname;
                        row.insertCell().textContent = match.user_id2;
                        row.insertCell().textContent = match.user2_nickname;
                        row.insertCell().textContent = match.status;
                        row.insertCell().textContent = new Date(match.created_at).toLocaleString();
                    });
                } else {
                    matchesTableBody.innerHTML = '<tr><td colspan="7" style="text-align:center;">暂无匹配历史</td></tr>';
                }
            }
        } catch (error) {
            console.error('加载匹配历史失败:', error);
             const matchesTableBody = document.getElementById('matchesTableBody');
            if(matchesTableBody) matchesTableBody.innerHTML = `<tr><td colspan="7" style="text-align:center;">${error.message}</td></tr>`;
        }
    }

    // 3. 加载聊天伙伴
    async function fetchChatPartners() {
        try {
            const response = await fetch(`${API_BASE_URL}/admin/users/${userId}/chat_partners`, {
                headers: { 'Authorization': `Bearer ${adminToken}` }
            });
            if (!response.ok) throw new Error(`获取聊天伙伴失败: ${response.statusText}`);
            const data = await response.json();
            const chatPartnersTableBody = document.getElementById('chatPartnersTableBody');
            if (chatPartnersTableBody) {
                chatPartnersTableBody.innerHTML = '';
                if (data.chat_partners && data.chat_partners.length > 0) {
                    data.chat_partners.forEach(partner => {
                        const row = chatPartnersTableBody.insertRow();
                        row.insertCell().textContent = partner.partner_id;
                        row.insertCell().textContent = partner.partner_nickname;
                        const avatarCell = row.insertCell();
                        if (partner.partner_avatar) {
                            const img = document.createElement('img');
                            img.src = partner.partner_avatar;
                            img.alt = partner.partner_nickname;
                            img.style.width = '40px';
                            img.style.height = '40px';
                            img.style.borderRadius = '50%';
                            avatarCell.appendChild(img);
                        } else {
                            avatarCell.textContent = 'N/A';
                        }
                        row.insertCell().textContent = partner.last_message || 'N/A';
                        row.insertCell().textContent = partner.last_message_time ? new Date(partner.last_message_time).toLocaleString() : 'N/A';
                        
                        const actionCell = row.insertCell();
                        const chatButton = document.createElement('a');
                        chatButton.href = `chat_history.html?user_id1=${userId}&user_id2=${partner.partner_id}`;
                        chatButton.textContent = '查看聊天';
                        chatButton.classList.add('chat-btn', 'button');
                        actionCell.appendChild(chatButton);
                    });
                } else {
                    chatPartnersTableBody.innerHTML = '<tr><td colspan="6" style="text-align:center;">暂无聊天伙伴</td></tr>';
                }
            }
        } catch (error) {
            console.error('加载聊天伙伴失败:', error);
            const chatPartnersTableBody = document.getElementById('chatPartnersTableBody');
            if(chatPartnersTableBody) chatPartnersTableBody.innerHTML = `<tr><td colspan="6" style="text-align:center;">${error.message}</td></tr>`;
        }
    }

    // 初始加载所有数据
    fetchUserDetails();
    fetchMatches();
    fetchChatPartners();
});
