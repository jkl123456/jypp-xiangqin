// 聊天列表功能初始化
document.addEventListener('DOMContentLoaded', function() {
    const chatList = document.getElementById('chat-list');
    const token = localStorage.getItem('token');
    const currentUserId = localStorage.getItem('user_id'); // 假设用户ID也存储在localStorage

    if (!token) {
        window.location.href = 'login.html'; // 如果没有token，重定向到登录页
        return;
    }

    let ws;

    function fetchTotalUnreadCount() {
        console.log('Attempting to fetch total unread count...'); // 添加日志
        if (!token) { // 再次检查 token，确保在函数调用时 token 仍然有效
            console.error('Token not available when trying to fetch total unread count.');
            return;
        }
        console.log('Token value before fetch:', token); // 打印 token 值
        try {
            fetch('http://14.103.133.136:5000/api/unread-count', {
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            })
            .then(response => {
                console.log('Received response from /api/unread-count (status):', response.status); 
                if (!response.ok) {
                    // 尝试读取响应体以获取更多错误信息
                    return response.text().then(text => {
                        console.error('Error response body from /api/unread-count:', text);
                        throw new Error(`HTTP error! status: ${response.status}, body: ${text}`);
                    }).catch(err => {
                        // 如果读取响应体也失败或不是文本
                        console.error('Failed to read error response body or not text:', err);
                        throw new Error(`HTTP error! status: ${response.status}, (could not read error body)`);
                    });
                }
                return response.json();
            })
            .then(data => {
                // 确保 data 不是在 !response.ok 时抛出的 Error 对象
                if (data instanceof Error) { 
                    // 这个错误应该已经被上一个 .catch() 捕获了，但作为安全措施
                    console.error('Error object passed to success handler:', data.message);
                    return; 
                }
                if (data && typeof data.unread_count !== 'undefined') {
                    updateTotalUnreadBadge(data.unread_count);
                    console.log('Total unread count fetched via API:', data.unread_count);
                } else {
                    console.error('Failed to get unread_count from API response or data is unexpected:', data);
                }
            })
            .catch(error => { // 这个 catch 会捕获 fetch 网络错误以及上面抛出的错误
                console.error('Error in fetch promise chain for /api/unread-count:', error.message);
            });
        } catch (e) {
            // 这个 catch 会捕获 fetch 调用本身（同步代码部分）的错误
            console.error('Synchronous error during fetch call for /api/unread-count:', e);
        }
    }

    function connectWebSocket() {
        const wsUrl = `ws://14.103.133.136:8766?token=${token}`;
        ws = new WebSocket(wsUrl);

        ws.onopen = function() {
            console.log('WebSocket connection established for chat list.');
            // WebSocket 连接成功后不再主动请求总未读数，由 HTTP API 处理
        };

        ws.onmessage = function(event) {
            const data = JSON.parse(event.data);
            console.log('Received message on chat list:', data);
            // 移除了 unread_count_update 的处理，因为现在通过 HTTP API 获取
            if (data.type === 'private_message' || data.type === 'room_message') {
                // 如果收到新消息，刷新聊天列表，并重新获取总未读数
                fetchChatList();
                fetchTotalUnreadCount(); // 新消息可能改变总未读数
            } else if (data.type === 'messages_marked_read') {
                // 消息被标记为已读，刷新列表，并重新获取总未读数
                fetchChatList();
                fetchTotalUnreadCount(); // 标记已读会改变总未读数
            }
        };

        ws.onerror = function(error) {
            console.error('WebSocket Error on chat list: ', error);
        };

        ws.onclose = function() {
            console.log('WebSocket connection closed on chat list. Attempting to reconnect...');
            // 简单重连逻辑
            setTimeout(connectWebSocket, 5000);
        };
    }

    function fetchChatList() {
        fetch('/api/chats', {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.chats) {
                renderChatList(data.chats);
            } else {
                console.error('Failed to load chat list:', data.message);
            }
        })
        .catch(error => console.error('Error fetching chat list:', error));
    }

    function renderChatList(chats) {
        chatList.innerHTML = ''; // 清空现有列表
        chats.forEach(chat => {
            const chatItem = document.createElement('div');
            chatItem.className = 'chat-item';
            chatItem.dataset.userId = chat.user_id; // 存储对方用户ID
            chatItem.dataset.userName = chat.nickname; // 存储对方用户名
            chatItem.dataset.isRoom = chat.is_room || false; // 标记是否为群聊
            chatItem.dataset.roomId = chat.room_id || ''; // 存储房间ID

            // 格式化时间
            let displayTime = '';
            if (chat.last_message_time) {
                const messageDate = new Date(chat.last_message_time);
                const today = new Date();
                if (messageDate.toDateString() === today.toDateString()) {
                    displayTime = messageDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                } else {
                    displayTime = messageDate.toLocaleDateString();
                }
            }
            
            // 确保 last_message 存在
            const lastMessageText = chat.last_message || '开始聊天吧！';


            // 构建头像 URL
            let avatarUrl = chat.avatar || 'assets/images/default-avatar.png';
            if (avatarUrl && !avatarUrl.startsWith('http') && !avatarUrl.startsWith('assets/')) {
                // 如果是相对路径且不是本地静态资源，则拼接 API_BASE_URL
                avatarUrl = `${CONFIG.API_BASE_URL}${avatarUrl}`;
            }

            chatItem.innerHTML = `
                <div class="avatar" style="background-image: url('${avatarUrl}')"></div>
                <div class="chat-info">
                    <div class="name">${chat.nickname}</div>
                    <div class="last-msg">${truncateText(lastMessageText, 20)}</div>
                </div>
                <div class="chat-meta">
                    <div class="time">${displayTime}</div>
                    ${chat.unread_count > 0 ? `<div class="unread">${chat.unread_count}</div>` : ''}
                </div>
            `;
            chatList.appendChild(chatItem);
        });

        // 为新渲染的列表项添加点击事件
        document.querySelectorAll('.chat-item').forEach(item => {
            item.addEventListener('click', function() {
                const targetUserId = this.dataset.userId;
                const targetUserName = this.dataset.userName;
                const isRoom = this.dataset.isRoom === 'true';
                const roomId = this.dataset.roomId;

                if (isRoom) {
                    // 跳转到群聊房间
                    // window.location.href = `chat-room.html?room_id=${roomId}&room_name=${targetUserName}`;
                    alert(`进入群聊: ${targetUserName} (功能待实现)`);
                } else {
                    // 私聊
                    if (ws && ws.readyState === WebSocket.OPEN && targetUserId) {
                        ws.send(JSON.stringify({
                            type: 'mark_as_read',
                            sender_id: parseInt(targetUserId) // 将当前聊天对象的ID作为sender_id发送
                        }));
                    }
                    // 跳转到私聊页面
                    window.location.href = `chat.html?user_id=${targetUserId}&name=${encodeURIComponent(targetUserName)}`;
                }
            });
        });
    }
    
    function truncateText(text, maxLength) {
        if (text.length > maxLength) {
            return text.substring(0, maxLength) + '...';
        }
        return text;
    }

    function updateTotalUnreadBadge(count) {
        const chatNavBadge = document.getElementById('chat-nav-badge');
        if (chatNavBadge) {
            if (count > 0) {
                chatNavBadge.textContent = count > 99 ? '99+' : count;
                chatNavBadge.style.display = 'flex'; // Ensure it's visible and styled as a badge
            } else {
                chatNavBadge.textContent = '';
                chatNavBadge.style.display = 'none';
            }
        }
    }

    // 初始化
    fetchChatList(); // fetchChatList 内部会渲染列表，包括单个未读数
    fetchTotalUnreadCount(); // 页面加载时通过 API 获取总未读数
    connectWebSocket(); 
});
