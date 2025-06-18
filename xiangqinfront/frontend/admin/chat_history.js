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
    const userId1 = params.get('user_id1'); // 通常是当前管理员视角下的用户
    const userId2 = params.get('user_id2'); // 聊天对象

    const chatMessagesContainer = document.getElementById('chatMessagesContainer');
    const loadMoreButton = document.getElementById('loadMoreMessages');
    const chatHistoryTitle = document.getElementById('chatHistoryTitle');
    const backToUserDetailsLink = document.getElementById('backToUserDetails');

    let currentPage = 1;
    const messagesPerPage = 50; // 与后端API一致

    if (!userId1 || !userId2) {
        alert('缺少用户ID参数');
        if (chatMessagesContainer) chatMessagesContainer.innerHTML = '<p>无法加载聊天记录，缺少用户ID。</p>';
        if (loadMoreButton) loadMoreButton.style.display = 'none';
        return;
    }

    if (chatHistoryTitle) {
        // 为了更友好地显示标题，可以尝试获取用户昵称，但这里简化处理
        chatHistoryTitle.textContent = `用户 ${userId1} 与 用户 ${userId2} 的聊天记录`;
    }
    if (backToUserDetailsLink) {
        backToUserDetailsLink.href = `user_details.html?id=${userId1}`;
    }


    async function fetchChatHistory(page = 1) {
        if (!chatMessagesContainer) return;
        try {
            const response = await fetch(
                `${API_BASE_URL}/admin/chats?user_id1=${userId1}&user_id2=${userId2}&page=${page}&per_page=${messagesPerPage}`, {
                headers: { 'Authorization': `Bearer ${adminToken}` }
            });

            if (response.status === 401) {
                localStorage.removeItem('adminToken');
                window.location.href = 'login.html';
                return;
            }
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.message || `获取聊天记录失败: ${response.statusText}`);
            }

            const data = await response.json();
            renderMessages(data.chat_history || [], page === 1);

            if (data.chat_history && data.chat_history.length < messagesPerPage) {
                if (loadMoreButton) loadMoreButton.style.display = 'none'; // 没有更多消息了
            } else {
                if (loadMoreButton) loadMoreButton.style.display = 'block';
            }
            currentPage = page;

        } catch (error) {
            console.error('加载聊天记录失败:', error);
            chatMessagesContainer.innerHTML = `<p>加载聊天记录时出错: ${error.message}</p>`;
            if (loadMoreButton) loadMoreButton.style.display = 'none';
        }
    }

    function renderMessages(messages, isFirstLoad) {
        if (!chatMessagesContainer) return;
        
        // messages 是按时间升序排列的 (API返回时已反转)
        messages.forEach(msg => {
            const messageDiv = document.createElement('div');
            messageDiv.classList.add('chat-message');

            // 判断消息是 userId1 发送的还是 userId2 发送的
            // API 返回的 sender_id 是实际发送者
            if (msg.sender_id == userId1) {
                messageDiv.classList.add('message-sender'); // 假设 userId1 是 "我" (右侧)
            } else {
                messageDiv.classList.add('message-receiver'); // userId2 是对方 (左侧)
            }
            
            const contentP = document.createElement('p');
            contentP.textContent = msg.message;
            messageDiv.appendChild(contentP);

            const metaDiv = document.createElement('div');
            metaDiv.classList.add('message-meta');
            metaDiv.textContent = `${msg.sender_nickname} - ${new Date(msg.created_at).toLocaleString()}`;
            messageDiv.appendChild(metaDiv);
            
            // 如果是加载更多，则在顶部插入旧消息
            if (!isFirstLoad && chatMessagesContainer.firstChild) {
                 chatMessagesContainer.insertBefore(messageDiv, chatMessagesContainer.firstChild);
            } else {
                 chatMessagesContainer.appendChild(messageDiv);
            }
        });

        if (isFirstLoad) {
            // 首次加载，滚动到底部
            chatMessagesContainer.scrollTop = chatMessagesContainer.scrollHeight;
        } else if (messages.length > 0) {
            // 加载更多后，保持滚动位置，让用户能看到新加载的旧消息的顶部
            // (或者可以尝试更复杂的滚动位置保持逻辑)
        }
    }

    if (loadMoreButton) {
        loadMoreButton.addEventListener('click', () => {
            fetchChatHistory(currentPage + 1);
        });
    }

    // 初始加载
    fetchChatHistory(currentPage);
});
