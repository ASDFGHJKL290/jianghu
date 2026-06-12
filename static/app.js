const{createApp,ref,computed,onMounted,nextTick,watch}=Vue;
createApp({
  setup(){
    /* ── 状态 ── */
    const messages      = ref({});
    const currentNpc    = ref("店小二");
    const inputText     = ref("");
    const loading       = ref(false);
    const typingMsgIdx  = ref(-1);
    const typingPos     = ref(0);
    let typingTimer     = null;
    const chatOpen      = ref(false);
    const activeTab     = ref("char");
    const toast         = ref("");
    const npcs          = ref([]);
    const quests        = ref([]);
    const chatBodyRef   = ref(null);
    const isRecording   = ref(false);
    let   mediaRecorder = null;
    let   audioChunks   = [];

    /* ── 章节进度系统 ── */
    const chapterInfo = ref({
      chapter: 0,
      title: "",
      advanced: false,
      completedAll: false
    });
    const giftReceived = ref(null); // 收到的礼物信息
    const showGiftModal = ref(false); // 礼物弹窗显示状态
    const outcomeInfo = ref(null);    // 结局信息
    const showOutcomeModal = ref(false); // 结局弹窗显示状态

    /* ── 围棋死活题状态 ── */
    const goActive      = ref(false);       // 是否显示棋盘
    const goProblemInfo = ref({});          // 题目信息
    const goBoard       = ref([]);          // 棋盘二维数组
    const goBoardSize   = ref(9);           // 棋盘大小
    const goSessionId   = ref("");          // 会话ID (quest_id)
    const goMessage     = ref("");          // 解决后消息
    const goMoveCount   = ref(0);           // 已走步数
    const goTotalMoves  = ref(0);           // 总需步数
    const goSolved      = ref(false);       // 是否已解
    const goError       = ref("");          // 错误提示

    /* ── 角色面板数据 ── */
    const playerName   = ref("江湖少侠");
    const playerTitle  = ref("江湖新秀");   // 同步 realm.title
    const playerAvatar = ref("/static/image/玩家.png");
    const hp           = ref(100);
    const maxHp        = ref(100);
    const silver       = ref(15);
    const rep          = ref(10);
    const gameDay      = ref(1);
    const mapFragments = computed(()=>{
      const frag=items.value.find(it=>it.name==='江湖地图碎片');
      return frag?frag.count:0;
    });

    /* ── 修为境界系统 ── */
    const realm = ref({
      level: 1,
      name: "初入江湖",
      title: "江湖新秀",
      total_exp: 0,
      progress_exp: 0,   // 当前境界内已积累
      need: 100,          // 突破到下一重所需
      progress: 0,         // 百分比 0-100
      next: "初窥门径",
      next_title: "江湖少侠",
      is_max: false,
    });
    const realmBreakthrough = ref(false); // 触发突破动画

    /* ── 新手引导状态 ── */
    const tutorialStep    = ref(0);     // 0未开始/1门派选择/2对话/3答题/4战斗/5送礼/6解锁地图/7完成
    const tutorialFaction= ref("");    // 选中的门派
    const tutorialModal  = ref(false); // 门派选择弹窗显示
    const tutorialHint   = ref("");    // 当前引导提示
    const tutQuestion    = ref(null);  // unused now, kept for compatibility
    const tutQNum       = ref(1);
    const tutTotalQ     = ref(3);

    /* ── 战斗系统数据 ── */
    const combatActive = ref(false);
    const combatState = ref({
      player_hp: 100,
      enemy_hp: 80,
      enemy_name: "黑衣刺客",
      status: "ongoing",
      round: 0
    });
    const weather = ref({type:"晴",date:"今日",desc:"碧空如洗"});
    const items = ref([
      {name:"女儿红",icon:"📶",count:1},
      {name:"碎银",  icon:"💰",count:0},
      {name:"青钢剑",icon:"⚔️",count:1},
      {name:"大还丹",icon:"💊",count:2},
    ]);
    const relations = ref([
      {npc:"店小二",  avatar:"/static/image/店小二.png",val:55},
      {npc:"武林盟主",avatar:"/static/image/武林盟主.png",val:30},
      {npc:"神秘大侠",avatar:"/static/image/fengwuhen.png",val:10},
      {npc:"扫地僧",  avatar:"/static/image/扫地僧.png",val:0},
      {npc:"洪七公",  avatar:"/static/image/洪七公.png",val:0},
      {npc:"任盈盈",  avatar:"/static/image/任盈盈.png",val:0},
      {npc:"风清扬",  avatar:"/static/image/风清杨.png",val:0},
      {npc:"黄衫女",  avatar:"/static/image/黄杉女.png",val:0},
      {npc:"唐巧",    avatar:"/static/image/tangqiao.png",val:0},
      {npc:"欧阳克",  avatar:"/static/image/欧阳克.png",val:0},
      {npc:"瑛姑",    avatar:"/static/image/瑛姑.png",val:0},
      {npc:"平一指",  avatar:"/static/image/pingyizhi.png",val:0},
      {npc:"任我行",  avatar:"/static/image/任我行.png",val:0},
    ]);

    /* ── 地图数据 ── */
    const allLocations = ref([
      {name:"悦来酒楼",  icon:"🏮",npc:"店小二",   unlocked:true,  x:200,y:420},
      {name:"武林盟主府",icon:"⚔️",npc:"武林盟主",  unlocked:true,  x:550,y:350},
      {name:"少林寺",    icon:"🙏",npc:"扫地僧",   unlocked:false, x:130,y:220},
      {name:"丐帮总舵",  icon:"🍜",npc:"洪七公",   unlocked:false, x:700,y:400},
      {name:"华山思过崖",icon:"⛰️",npc:"风清扬",   unlocked:false, x:700,y:180},
      {name:"桃花岛",    icon:"🌸",npc:"黄衫女",   unlocked:false, x:580,y:90},
      {name:"四川唐门",  icon:"🦂",npc:"唐巧",     unlocked:false, x:60, y:380},
      {name:"黑木崖",    icon:"🌑",npc:"任盈盈",   unlocked:false, x:720,y:480},
      {name:"日月神教",  icon:"🔥",npc:"任我行",   unlocked:false, x:200,y:80},
      {name:"白驼山庄",  icon:"🐍",npc:"欧阳克",   unlocked:false, x:400,y:300},
      {name:"黑龙潭",    icon:"💧",npc:"瑛姑",     unlocked:false, x:340,y:140},
      {name:"江湖游医",  icon:"💊",npc:"平一指",   unlocked:false, x:500,y:200},
      {name:"天涯海角",  icon:"🌫️",npc:"神秘大侠", unlocked:true,  x:480,y:170},
    ]);
    const mapLocations = computed(()=>
      allLocations.value.map(loc=>({...loc,unlocked:loc.unlocked||loc.npc===currentNpc.value}))
    );

    /* ── 计算属性 ── */
    const currentMessages = computed(()=>messages.value[currentNpc.value]||[]);
    const currentAvatar   = computed(()=>(npcs.value.find(n=>n.name===currentNpc.value)||{}).avatar||"/static/image/店小二.png");
    const currentLocation = computed(()=>(npcs.value.find(n=>n.name===currentNpc.value)||{}).location||"未知");
    const weatherDisplay = computed(()=>weather.value.type?weather.value.type:"加载中");

    /* ── Toast ── */
    function showToast(msg,dur=3000){toast.value=msg;setTimeout(()=>{toast.value="";},dur);}

    /* ── 礼物弹窗 ── */
    function dismissGift(){
      showGiftModal.value = false;
      giftReceived.value = null;
    }

    /* ── NPC认知模拟面板 ── */
    const npcInfo = ref(null);
    const showNpcInfo = ref(false);
    async function openNpcInfo(){
      showNpcInfo.value = true;
      npcInfo.value = null;
      try{
        const r = await fetch(`/api/npc/info/${currentNpc.value}`);
        const d = await r.json();
        npcInfo.value = d;
      }catch(e){
        npcInfo.value = { error: "加载失败" };
      }
    }
    function closeNpcInfo(){
      showNpcInfo.value = false;
    }

    /* ── 结局弹窗 ── */
    function dismissOutcome(){
      showOutcomeModal.value = false;
      outcomeInfo.value = null;
    }

    /* ── 突破高亮动画 ── */
    function triggerBreakthrough(){
      realmBreakthrough.value = true;
      nextTick(()=>{
        const el = document.querySelector('.realm-box');
        if(el){ el.classList.remove('breakthrough'); void el.offsetWidth; el.classList.add('breakthrough'); }
      });
      setTimeout(()=>{ realmBreakthrough.value = false; }, 2000);
    }

    /* ── 地图地点点击 ── */
    async function onLocClick(loc){
      const realLoc = allLocations.value.find(l=>l.name===loc.name);
      if(realLoc && !realLoc.unlocked && realLoc.npc!==currentNpc.value){
        showToast("「"+loc.name+"」尚未解锁,需要更多地图碎片");
        return;
      }
      if(currentNpc.value !== loc.npc){
        currentNpc.value = loc.npc;
        chatOpen.value = false;
        showToast("前往「"+loc.name+"」");
        await nextTick();
        return;
      }
      await openChat(loc.npc);
    }

    /* ── 打开对话 ── */
    async function openChat(npcName){
      currentNpc.value = npcName;
      chatOpen.value = true;
      if(!messages.value[npcName]){
        messages.value[npcName] = [];
        const npc = npcs.value.find(n=>n.name===npcName);
        if(npc&&npc.greeting) messages.value[npcName].push({role:"assistant",content:npc.greeting});
      }
      await nextTick();
      scrollBottom();
    }

    function closeChat(){chatOpen.value=false;}

    /* ── 围棋死活题 ── */
    async function openGoBoard(problemInfo){
      goProblemInfo.value = problemInfo;
      goActive.value = true;
      goSessionId.value = problemInfo.quest_id;

      // 先检查后端是否有会话（刷新页面恢复用）
      try{
        const statusR = await fetch(`/api/go/status/${problemInfo.quest_id}`);
        const statusD = await statusR.json();
        if(statusD.active){
          // 恢复已有会话
          goBoard.value = statusD.board;
          goBoardSize.value = statusD.board_size || 9;
          goSolved.value = statusD.solved;
          goMoveCount.value = statusD.moves || 0;
          goError.value = "";
          if(statusD.solved){
            goMessage.value = "棋局已破解！";
          } else {
            goMessage.value = `你的回合（第${statusD.moves || 0}手）`;
          }
          return;
        }
      }catch(e){ /* 忽略，走新建流程 */ }

      // 新建会话
      goSolved.value = false;
      goMessage.value = "";
      goError.value = "";
      goMoveCount.value = 0;
      fetch(`/api/go/start/${problemInfo.quest_id}/${problemInfo.go_problem_id}`, {method:"POST"})
        .then(r=>r.json())
        .then(d=>{
          goBoard.value = d.board;
          goBoardSize.value = d.board_size || 9;
          if(d.description || d.hint){
            goProblemInfo.value = {
              ...goProblemInfo.value,
              desc: [d.description, d.hint ? '提示：'+d.hint : ''].filter(Boolean).join('\n'),
            };
          }
        });
    }

    const gridWidth  = computed(() => 60 + (goBoardSize.value - 1) * 36);
    const gridHeight = computed(() => 60 + (goBoardSize.value - 1) * 36);

    function closeGoBoard(){
      goActive.value = false;
      goBoard.value = [];
    }

    async function handleGoClick(col, row){
      if(goSolved.value) return;
      goError.value = "";
      goMessage.value = "KataGo 思考中...";
      try{
        const r = await fetch(`/api/go/move/${goSessionId.value}?col=${col}&row=${row}`, {method:"POST"});
        const d = await r.json();
        if(d.error){ goError.value = d.error; goMessage.value = ""; return; }
        goBoard.value = d.board;
        if(d.solved){
          goSolved.value = true;
          const summary = (d.summary || '活了！').replace(/链#\d+/g, '棋块');
          goMessage.value = `棋局破解！${summary} 风清扬微微颔首：'少侠前途无量。'`;

          // 通知后端任务步骤完成
          const resolveR = await fetch(`/api/go/resolve/${goSessionId.value}`, {method:"POST"});
          const resolveD = await resolveR.json();
          if(resolveD.completed){
            const ri = resolveD.reward_info || {};
            const line = resolveD.npc_line || ri.npc_line || '';
            const reward = resolveD.reward || ri.reward || '';
            goMessage.value = line || `任务完成！奖励：${reward}`;
            await loadQuests();  // 实时刷新任务列表
            await load存档();   // 实时刷新银两/背包/修为
          }
        } else if(d.summary){
          goMessage.value = d.summary + (d.opponent_move ? ` · 对手应 ${d.opponent_move}` : '');
        } else {
          goMessage.value = "你的回合";
        }
      }catch(e){ goError.value = "网络错误"; goMessage.value = ""; }
    }

    async function evaluateGo(){
      if(!goSessionId.value || goSolved.value) return;
      goMessage.value = "判定中...";
      try{
        const r = await fetch(`/api/go/evaluate/${goSessionId.value}`, {method:"POST"});
        const d = await r.json();
        if(d.alive){
          goSolved.value = true;
          goMessage.value = d.message || "棋已活！";
          const resolveR = await fetch(`/api/go/resolve/${goSessionId.value}`, {method:"POST"});
          const resolveD = await resolveR.json();
          if(resolveD.completed){
            const ri = resolveD.reward_info || {};
            const line = resolveD.npc_line || ri.npc_line || '';
            const reward = resolveD.reward || ri.reward || '';
            goMessage.value = line || `任务完成！奖励：${reward}`;
            await loadQuests();  // 实时刷新任务列表
            await load存档();   // 实时刷新银两/背包/修为
          }
        } else {
          goMessage.value = d.message || "还没活，继续下";
        }
      }catch(e){ goMessage.value = "判定失败"; }
    }

    // 棋盘到SVG坐标
    function goCellX(col){ return 30 + col * 36; }
    function goCellY(row){ return 30 + (goBoardSize.value - 1 - row) * 36; }
    const COL_LABELS = "ABCDEFGHJKLMNOPQRST";

    // 生成围棋SVG内部HTML（避免模板中v-for解析问题）
    const goSvgHtml = computed(() => {
      const size = goBoardSize.value;
      if (!size) return '';
      const cell = 36;
      const margin = 30;
      const inner = (size - 1) * cell;
      let h = '';
      // 网格线
      for (let i = 0; i < size; i++) {
        const p = margin + i * cell;
        h += `<line x1="${p}" y1="${margin}" x2="${p}" y2="${margin + inner}" stroke="#555" stroke-width="1"/>`;
        h += `<line x1="${margin}" y1="${p}" x2="${margin + inner}" y2="${p}" stroke="#555" stroke-width="1"/>`;
      }
      // 星位
      const stars = size === 9 ? [[2,2],[2,6],[6,2],[6,6],[4,4]]
        : size === 13 ? [[3,3],[3,9],[9,3],[9,9],[6,6]]
        : [[3,3],[3,9],[9,3],[9,9]]; // 19路
      if (size === 19) stars.push([15,3],[15,9],[15,15],[3,15],[9,15]);
      for (const [sx, sy] of stars) {
        if (sx < size && sy < size) {
          h += `<circle cx="${margin + sx * cell}" cy="${margin + sy * cell}" r="4" fill="#555"/>`;
        }
      }
      // 坐标标签
      for (let i = 0; i < size; i++) {
        h += `<text x="${margin + i * cell}" y="${margin - 8}" text-anchor="middle" fill="#666" font-size="11">${COL_LABELS[i]}</text>`;
        h += `<text x="${margin - 14}" y="${margin + i * cell + 4}" text-anchor="middle" fill="#666" font-size="11">${size - i}</text>`;
      }
      // 棋子
      const board = goBoard.value || [];
      for (let ri = 0; ri < board.length; ri++) {
        const row = board[ri];
        if (!row) continue;
        for (let ci = 0; ci < row.length; ci++) {
          if (row[ci]) {
            const cx = margin + ci * cell;
            const cy = margin + ri * cell;
            const isB = row[ci] === 'B';
            h += `<circle cx="${cx}" cy="${cy}" r="16" fill="${isB ? '#222' : '#fff'}" stroke="${isB ? '#111' : '#ccc'}" stroke-width="1.5" data-goci="${ci}" data-gori="${ri}" style="cursor:pointer"/>`;
          }
        }
      }
      // 可落子点（透明点击区域，仅空位且未解决）
      if (!goSolved.value) {
        for (let ri = 0; ri < board.length; ri++) {
          const row = board[ri];
          if (!row) continue;
          for (let ci = 0; ci < row.length; ci++) {
            if (!row[ci]) {
              const cx = margin + ci * cell;
              const cy = margin + ri * cell;
              h += `<circle cx="${cx}" cy="${cy}" r="16" fill="transparent" class="go-cell" data-goci="${ci}" data-gori="${ri}" style="cursor:pointer"/>`;
            }
          }
        }
      }
      return h;
    });

    // 点击SVG事件委托
    function handleSvgClick(e) {
      const el = e.target;
      if (!el || !el.dataset) return;
      const ci = parseInt(el.dataset.goci);
      const ri = parseInt(el.dataset.gori);
      if (isNaN(ci) || isNaN(ri)) return;
      handleGoClick(ci, ri);
    }

    /* ── 发送消息（流式） ── */
    async function sendMessage(){
      const text=inputText.value.trim();
      if(!text||loading.value)return;
      if(typingTimer){clearInterval(typingTimer);typingTimer=null;}
      if(typingMsgIdx.value>=0&&currentNpc.value){
        const prevMsgs=messages.value[currentNpc.value];
        if(prevMsgs&&prevMsgs[typingMsgIdx.value]){
          prevMsgs[typingMsgIdx.value].content=prevMsgs[typingMsgIdx.value]._full||prevMsgs[typingMsgIdx.value].content;
          delete prevMsgs[typingMsgIdx.value]._full;
        }
        typingMsgIdx.value=-1;
      }
      const npc=currentNpc.value;
      if(!messages.value[npc])messages.value[npc]=[];
      messages.value[npc].push({role:"user",content:text});
      inputText.value="";
      loading.value=true;
      await nextTick();
      scrollBottom();

      try{
        const r=await fetch("/api/chat/stream",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({message:text,npc_name:npc})});
        const reader=r.body.getReader();
        const decoder=new TextDecoder();
        let reply=""; let finalData=null;
        const msgIdx=messages.value[npc].length;
        messages.value[npc].push({role:"assistant",content:""});
        let buf="";

        while(true){
          const{done,value}=await reader.read();
          if(done)break;
          buf+=decoder.decode(value,{stream:true});
          // 解析 SSE 事件
          const lines=buf.split("\n\n");
          buf=lines.pop()||""; // 保留不完整的最后一段
          for(const block of lines){
            if(!block.trim())continue;
            let data="";
            for(const line of block.split("\n")){
              if(line.startsWith("data:")) data=line.slice(5).trim();
            }
            if(!data)continue;
            try{const evt=JSON.parse(data);
              if(evt.type==="token"){
                reply+=evt.content;
                const m=messages.value[npc][msgIdx];
                if(m)m.content=reply;
                scrollBottom();
              }else if(evt.type==="done"){
                finalData=evt;
              }
            }catch(e){}
          }
        }
        loading.value=false;
        if(!finalData)return;

        const d=finalData;
        reply=d.reply||reply;
        const m=messages.value[npc][msgIdx];
        if(m)m.content=reply;

        // TTS
        const em=window._emotionMap?.[d.emotion_state?.primary]||{speed:1.0,pitch:1.0,volume:50};
        const tfr=new FormData();
        tfr.append("text",reply);tfr.append("npc_name",npc);
        tfr.append("emotion",d.emotion_state?.primary||"neutral");
        tfr.append("speed",em.speed);tfr.append("pitch",em.pitch);tfr.append("volume",em.volume);
        try{const tr=await fetch("/api/tts",{method:"POST",body:tfr});const td=await tr.json();if(td.audio_url)playAudio(td.audio_url);}catch(e){}

        if(d.new_quests&&d.new_quests.length>0){
          d.new_quests.forEach(q=>{messages.value[npc].push({role:"system",content:"📜 "+q.title+"\n"+q.desc});});
          await loadQuests();
        }
        if(d.gift&&d.gift.item){
          giftReceived.value=d.gift;
          showGiftModal.value=true;
          messages.value[npc].push({role:"system",content:"🎁 "+d.gift.from+" 赠送了你 "+d.gift.item+" ！"});
        }
        if(d.new_relation!=null){
          const idx=relations.value.findIndex(r=>r.name===npc);
          if(idx>=0)relations.value[idx].intimacy=d.new_relation;
        }

        // 围棋死活题触发：推送到对话，等玩家点击
        if(d.go_problem && d.go_problem.go_problem_id){
          messages.value[npc].push({
            role:"go_prompt",
            content: d.go_problem.desc || "风清扬摆下一局棋，等你来破。",
            goProblemData: d.go_problem
          });
        }

        // 后端也推送 tutorial_advanced(兜底)
        if(d.tutorial_advanced&&tutorialStep.value<4){
          tutorialStep.value=4;
          showToast("📜「初入江湖」完成!\n⚔️ 教学战斗触发中...",5000);
        }
      }catch(e){
        messages.value[npc].push({role:"assistant",content:"⚠️ 网络错误,请检查服务器是否启动"});
      }finally{loading.value=false;await nextTick();scrollBottom();}
    }

    async function sendQuick(q){inputText.value=q;sendMessage();}
    function scrollBottom(){if(chatBodyRef.value)chatBodyRef.value.scrollTop=chatBodyRef.value.scrollHeight;}

    /* ── TTS ── */
    async function playAudio(url){
      if(!url)return;
      const prev=document.getElementById("tts-audio");
      if(prev)prev.remove();
      const a=document.createElement("audio");a.id="tts-audio";a.src=url;a.autoplay=true;
      document.body.appendChild(a);
      a.play().catch(()=>{});
    }

    /* ── 录音 ── */
    async function startRecording(){
      if(isRecording.value||loading.value)return;
      try{
        const stream=await navigator.mediaDevices.getUserMedia({audio:true});
        mediaRecorder=new MediaRecorder(stream,{mimeType:"audio/webm"});
        audioChunks=[];
        mediaRecorder.ondataavailable=e=>{if(e.data.size>0)audioChunks.push(e.data);};
        mediaRecorder.start();isRecording.value=true;
      }catch(e){showToast("请允许麦克风权限");}
    }
    async function stopRecording(){
      if(!isRecording.value||!mediaRecorder)return;
      isRecording.value=false;
      mediaRecorder.stop();
      mediaRecorder.stream.getTracks().forEach(t=>t.stop());
      await new Promise(r=>setTimeout(r,300));
      if(audioChunks.length===0){showToast("未检测到音频");return;}
      const blob=new Blob(audioChunks,{type:"audio/webm"});
      const form=new FormData();form.append("file",blob,"recording.webm");
      showToast("🎤 识别中...");
      try{
        const r=await fetch("/api/stt",{method:"POST",body:form});
        const d=await r.json();
        if(d.text){inputText.value=d.text;await sendMessage();}else{showToast("未识别到内容");}
      }catch(e){showToast("语音识别失败");}
    }

    /* ── 地图状态同步 ── */
    async function loadMapStatus(){
      try{
        const r=await fetch("/api/map/status");
        const d=await r.json();
        const unlocked=d.unlocked||[];
        // 动态覆盖写死的 unlocked 状态
        allLocations.value.forEach(loc=>{
          loc.unlocked=unlocked.includes(loc.name);
        });
      }catch(e){console.error("[地图状态]",e);}
    }

    /* ── 任务 ── */
    async function loadQuests(){
      try{const r=await fetch("/api/quest/progress");const d=await r.json();quests.value=d.quests||[];}catch(e){}
    }
    async function abandonQuest(q){
      if(!confirm("确定放弃「"+q.title+"」?"))return;
      try{const r=await fetch("/api/quest/abandon",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({qid:q.qid})});const d=await r.json();if(d.status==="ok")await loadQuests();}catch(e){}
    }

    /* ── 存档同步 ── */
    async function load存档(){
      try{
        const [playerRes,relRes]=await Promise.all([
          fetch("/api/player"),
          fetch("/api/relation"),
        ]);
        const pd=await playerRes.json();
        if(pd.game_day)gameDay.value=pd.game_day;
        if(pd.silver!=null&&pd.silver!==undefined)silver.value=pd.silver;
        if(pd.items)items.value=pd.items;
        if(pd.realm){
          realm.value = pd.realm;
          playerTitle.value = pd.realm.title || realm.value.title;
        }
        await loadMapStatus(); // 刷新图碎和解锁状态
        const rd=await relRes.json();
        // 好感度列表 = 已解锁地点的NPC(默认50)+ API覆盖真实数据
        const relList = allLocations.value
            .filter(l => l.unlocked)
            .map(l => {
                const data = rd[l.npc];
                return {
                    npc: l.npc,
                    val: data ? (typeof data === 'object' ? data.intimacy : data) : 50,
                    avatar: (npcs.value.find(x=>x.name===l.npc)||{}).avatar || "/static/image/店小二.png",
                };
            });
        relations.value = relList;
      }catch(e){console.error("[存档加载]",e);}
    }

    window.addEventListener('beforeunload',()=>{
      navigator.sendBeacon&&navigator.sendBeacon("/api/player","{}");
    });

    /* ── 初始化 ── */
    async function init(){
      try{
        const [nr,r,hr]=await Promise.all([fetch("/api/npcs"),fetch("/api/weather"),fetch("/api/chat/history")]);
        npcs.value=await nr.json();
        const wd=await r.json();if(wd&&wd.type)weather.value=wd;
        // 恢复聊天记录
        try{
          const hd=await hr.json();
          if(hd.messages&&Object.keys(hd.messages).length>0){
            messages.value=hd.messages;
          }
        }catch(e){/* 无历史，忽略 */}
        await Promise.all([load存档(),loadQuests(),loadTutorialStatus()]); // load存档 内部已刷新地图状态
      }catch(e){console.error("[init]",e);}
    }

    // 聊天记录自动保存（防抖1.5秒）
    let _saveTimer = null;
    function scheduleSave(){
      clearTimeout(_saveTimer);
      _saveTimer = setTimeout(async ()=>{
        try{
          await fetch("/api/chat/history",{
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body: JSON.stringify({messages: messages.value}),
          });
        }catch(e){/* 忽略保存错误 */}
      }, 1500);
    }
    // 监听 messages 变化自动保存
    watch(messages, ()=>{ scheduleSave(); }, {deep: true});
    // 页面关闭前最后一次保存
    window.addEventListener("beforeunload", ()=>{
      fetch("/api/chat/history", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({messages: messages.value}),
        keepalive: true,
      });
    });

    /* ── 新手引导 ── */
    async function loadTutorialStatus(){
      try{
        const r=await fetch("/api/tutorial/status");
        const d=await r.json();
        tutorialStep.value=d.step||0;
        tutorialFaction.value=d.faction||"";
        // Step 0 = 门派选择
        if(tutorialStep.value===0){
          tutorialModal.value=true;
        }
        // 指引现在由任务面板(index.html)持久显示,不需要在这里处理
      }catch(e){console.error("[tutorial]",e);}
    }

    // 每60秒后台刷邮箱未读数
    setInterval(async () => {
      try {
        const r = await fetch("/api/mailbox");
        const d = await r.json();
        if (d && d.unread !== undefined) {
          mailbox.value = d.messages || [];
        }
      } catch (e) { /* silent */ }
    }, 60000);

    async function selectFaction(f){
      try{
        const r=await fetch("/api/tutorial/start",{
          method:"POST",
          headers:{"Content-Type":"application/json"},
          body:JSON.stringify({faction:f})
        });
        const d=await r.json();
        tutorialStep.value=d.step||2;
        tutorialFaction.value=d.faction||f;
        tutorialModal.value=false;
        // 更新数据
        if(d.player_items)items.value=d.player_items;
        if(d.realm){realm.value=d.realm;playerTitle.value=d.realm.title||realm.value.title;}
        showToast("🎉 门派选择完成!",3000);
        // 打开店小二开始引导对话
        await openChat("店小二");
        if(d.reply){
          messages.value["店小二"].push({role:"assistant",content:d.reply});
          await nextTick();scrollBottom();
        }
      }catch(e){showToast("门派选择失败");}
    }

    async function markCombatWon(){
      if(tutorialStep.value!==4)return;
      try{
        const r=await fetch("/api/tutorial/complete-step",{
          method:"POST",
          headers:{"Content-Type":"application/json"},
          body:JSON.stringify({action:"combat_won"})
        });
        const d=await r.json();
        console.log("[DEBUG] combat_won response:", d);
        tutorialStep.value=d.step||5;
        console.log("[DEBUG] tutorialStep now:", tutorialStep.value);
        if(d.message)showToast(d.message,4000);
        if(d.realm){realm.value=d.realm;playerTitle.value=d.realm.title||realm.value.title;}
      }catch(e){console.error("[DEBUG] markCombatWon error:", e);}
    }

    async function markGiftSuccess(){
      if(tutorialStep.value!==5)return;
      try{
        const r=await fetch("/api/tutorial/complete-step",{
          method:"POST",
          headers:{"Content-Type":"application/json"},
          body:JSON.stringify({action:"gift_success"})
        });
        const d=await r.json();
        tutorialStep.value=d.step||6;
        showToast("🎉 送礼成功!引导即将完成!",3000);
      }catch(e){}
    }

    async function completeTutorial(){
      try{
        const r=await fetch("/api/tutorial/complete-step",{
          method:"POST",
          headers:{"Content-Type":"application/json"},
          body:JSON.stringify({action:"tutorial_done"})
        });
        const d=await r.json();
        tutorialStep.value=7;
        showToast("🏆 江湖之路,由此开始!",5000);
        // 指引现在由任务面板(index.html)持久显示
      }catch(e){}
    }

    /* ── 战斗系统 ── */
    async function startCombat(){
      try{
        const r = await fetch("/api/combat/start",{
          method:"POST",
          headers:{"Content-Type":"application/json"},
          body:JSON.stringify({action:"start",npc_name:currentNpc.value})
        });
        const d = await r.json();
        combatActive.value = true;
        combatState.value = {
          player_hp: d.player_hp,
          enemy_hp: d.enemy_hp,
          enemy_max: d.enemy_hp,
          enemy_name: d.enemy_name,
          status: "ongoing",
          round: 0
        };
        if(d.realm){ realm.value = d.realm; playerTitle.value = d.realm.title || realm.value.title; }
        messages.value[currentNpc.value].push({role:"system",content:d.opening_text});
        await nextTick();
        scrollBottom();
        showToast("⚔️ 战斗开始!");
      }catch(e){showToast("战斗启动失败");}
    }

    async function combatAction(action){
      if(loading.value)return;
      loading.value = true;
      try{
        const r = await fetch("/api/combat/action",{
          method:"POST",
          headers:{"Content-Type":"application/json"},
          body:JSON.stringify({action,npc_name:currentNpc.value})
        });
        const d = await r.json();

        // 后端返回 reset_combat → 战斗状态已失效,自动重置
        if(d.reset_combat){
          combatActive.value=false;
          showToast(d.error||"战斗已结束");
          loading.value=false;await nextTick();scrollBottom();return;
        }

        messages.value[currentNpc.value].push({role:"assistant",content:d.reply});

        if(d.combat_result){
          const oldPh = combatState.value.player_hp;
          const oldEh = combatState.value.enemy_hp;
          const newPlayerHp = d.combat_result.hp ?? oldPh;
          const newEnemyHp = d.combat_result.enemy_hp ?? oldEh;
          const finalPh = Math.max(0, Math.min(100, Math.min(newPlayerHp, oldPh)));
          const finalEh = Math.max(0, Math.min(combatState.value.enemy_max || 80, Math.min(newEnemyHp, oldEh)));
          combatState.value.player_hp = finalPh;
          combatState.value.enemy_hp = finalEh;
          combatState.value.status = d.combat_result.status;
        }

        // 境界/修为更新
        if(d.realm){ realm.value = d.realm; playerTitle.value = d.realm.title || realm.value.title; }

        if(d.reward){
          if(d.silver!=null)silver.value=d.silver;
          showToast(`🎉 战斗胜利!获得 ${d.reward.silver}两,${d.reward.exp}修为`);
          await load存档();
        }
        if(d.combat_result && d.combat_result.status !== "ongoing"){
          combatActive.value = false;
          if(d.combat_result.status === "defeat"){
            showToast("💀 战斗失败,休息片刻恢复HP");
            hp.value = Math.floor(hp.value * 0.5);
          }else if(d.combat_result.status === "escape"){
            showToast("🏃 成功逃脱");
          }
        }
      }catch(e){
        showToast("战斗行动失败");
      }finally{
        loading.value = false;
        await nextTick();
        scrollBottom();
      }
    }

    const quickQuestions=["降龙十八掌是谁创的?","华山剑气之争是怎么回事?","少林寺扫地僧是什么来头?","金庸十四部是什么?","江湖最厉害的暗器是什么?"];

    const itemDetail = ref(null);
    const itemResult = ref("");
    const selectedNpcForGift = ref("店小二");
    const shopItems = ref({});
    const shopLoading = ref(false);

    // 邮箱
    const mailbox = ref([]);
    const unreadMailCount = computed(() => mailbox.value.filter(m => !m.read).length);
    const selectedMail = ref(null);       // 当前选中的邮件（详情弹窗）
    const mailDetailOpen = ref(false);    // 详情弹窗是否打开
    let mailAutoTimer = null;              // 自动关闭定时器

    // 将邮箱消息按 chain_id 分组，保持原有顺序
    const mailboxGroups = computed(() => {
      const msgs = mailbox.value;
      const groups = [];
      let currentChainId = null;
      let currentChain = null;
      for (const m of msgs) {
        if (m.chain_id) {
          if (m.chain_id !== currentChainId) {
            // 新的事件链
            currentChainId = m.chain_id;
            currentChain = { isChain: true, chainId: m.chain_id, messages: [] };
            groups.push(currentChain);
          }
          currentChain.messages.push(m);
        } else {
          // 独立消息
          currentChainId = null;
          groups.push({ isChain: false, messages: [m] });
        }
      }
      return groups;
    });

    async function loadMailbox() {
      try {
        const r = await fetch("/api/mailbox");
        const d = await r.json();
        mailbox.value = d.messages || [];
      } catch (e) { console.error("[邮箱加载]", e); }
    }

    async function readMail(msg) {
      try {
        await fetch("/api/mailbox/read", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message_ids: [msg.id] })
        });
        msg.read = true;
      } catch (e) { console.error("[标记已读]", e); }
    }

    function openMailDetail(msg) {
      selectedMail.value = msg;
      mailDetailOpen.value = true;
      if (!msg.read) readMail(msg);
      startMailAutoClose();
    }

    function startMailAutoClose() {
      clearMailAutoClose();
      mailAutoTimer = setTimeout(() => { mailDetailOpen.value = false; }, 4000);
    }

    function clearMailAutoClose() {
      if (mailAutoTimer) { clearTimeout(mailAutoTimer); mailAutoTimer = null; }
    }

    function closeMailDetail() {
      mailDetailOpen.value = false;
      clearMailAutoClose();
    }

    async function deleteMail(msg) {
      await fetch(`/api/mailbox/${msg.id}?user_id=default`, { method: "DELETE" });
      mailbox.value = mailbox.value.filter(m => m.id !== msg.id);
      if (selectedMail.value && selectedMail.value.id === msg.id) {
        closeMailDetail();
      }
    }

    function handleMailAction(msg) {
      const link = msg.action_link;
      if (!link) return;
      if (link.type === "npc") {
        // 切换NPC对话
        const npcName = link.target;
        if (npcName && npcs.value.find(n => n.name === npcName)) {
          currentNpc.value = npcName;
          openChat(npcName);
          closeMailDetail();
        }
      } else if (link.type === "location") {
        // 切换地点（如果有地图切换功能）
        const locName = link.target;
        closeMailDetail();
        // 尝试通过地图的location切换
        if (window.switchLocation) {
          window.switchLocation(locName);
        }
      }
      mailDetailOpen.value = false;
    }

    async function openItemDetail(item){
      try{
        const r=await fetch("/api/item/effects");
        const d=await r.json();
        const eff=d.effects||{};
        const e=eff[item.name]||{};
        itemDetail.value={
          ...item,
          effectDesc: e.desc||"效果未知",
          effectType: e.type,
          canUse: e.type&&e.type!=="equip",
          useBtnText: e.type==="hp"?"💊 使用(恢复"+e.value+"HP)":
                    e.type==="favor"?"🍶 赠送NPC":
                    e.type==="silver"?"💰 收入囊中":
                    "🔧 使用",
          needSelectNpc: e.type==="favor",
        };
        itemResult.value="";
      }catch(e2){
        itemDetail.value={...item,effectDesc:"效果未知",canUse:false,useBtnText:"使用"};
      }
    }

    async function useItem(item){
      if(item.count<=0){itemResult.value="道具已用完";return;}
      try{
        const fd=new FormData();
        fd.append("item_name",item.name);
        if(itemDetail.value && itemDetail.value.needSelectNpc){
          fd.append("target_npc", selectedNpcForGift.value);
        }
        const r=await fetch("/api/item/use",{method:"POST",body:fd});
        const d=await r.json();
        if(d.ok){
          itemResult.value=d.message;
          if(d.items)items.value=d.items;
          if(d.applied&&d.applied.hp){
            hp.value=Math.min(hp.value+d.applied.hp,maxHp.value);
          }
          if(d.applied&&d.applied.silver){
            silver.value+=d.applied.silver;
          }
          if(d.applied&&d.applied.favor){
            const npcName = d.applied.favor.npc;
            const relIdx = relations.value.findIndex(r=>r.npc===npcName);
            if(relIdx>=0){
              relations.value[relIdx].val = d.applied.favor.value;
            }
          }
          if(itemDetail.value)itemDetail.value.count=Math.max(0,itemDetail.value.count-1);
        }else{
          itemResult.value=d.error||"使用失败";
        }
      }catch(e2){
        itemResult.value="网络错误";
      }
    }

    /* ── 商店 ── */
    async function loadShop(){
      try{
        const r=await fetch("/api/shop/items");
        const d=await r.json();
        shopItems.value=d.items||{};
      }catch(e){console.error("[商店加载]",e);}
    }

    async function buyItem(itemName){
      if(shopLoading.value)return;
      shopLoading.value=true;
      try{
        const r=await fetch("/api/shop/buy",{
          method:"POST",
          headers:{"Content-Type":"application/json"},
          body:JSON.stringify({item_name:itemName,count:1})
        });
        const d=await r.json();
        if(d.ok){
          showToast(d.message);
          if(d.silver!=null)silver.value=d.silver;
          if(d.items)items.value=d.items;
          if(d.realm){ realm.value = d.realm; playerTitle.value = d.realm.title || realm.value.title; }
          await loadShop();
          await loadMapStatus(); // 购买图碎后刷新解锁状态
        }else{
          showToast(d.error||"购买失败");
        }
      }catch(e){
        showToast("购买失败");
      }finally{
        shopLoading.value=false;
      }
    }

    onMounted(init);

    return{
      messages,currentNpc,inputText,loading,chatOpen,activeTab,toast,
      npcs,quests,chatBodyRef,isRecording,quickQuestions,
      playerName,playerTitle,hp,maxHp,silver,rep,gameDay,mapFragments,items,relations,
      currentMessages,currentAvatar,currentLocation,weatherDisplay,mapLocations,
      realm,realmBreakthrough,
      tutorialStep,tutorialFaction,tutorialModal,tutorialHint,
      tutQuestion,tutQNum,tutTotalQ,
      selectFaction,markCombatWon,markGiftSuccess,completeTutorial,
      showToast,openChat,closeChat,onLocClick,sendMessage,sendQuick,
      combatActive,combatState,startCombat,combatAction,
      startRecording,stopRecording,abandonQuest,
      chapterInfo,giftReceived,showGiftModal,dismissGift,
      outcomeInfo,showOutcomeModal,dismissOutcome,
      npcInfo,showNpcInfo,openNpcInfo,closeNpcInfo,
      itemDetail,itemResult,selectedNpcForGift,openItemDetail,useItem,
      shopItems,shopLoading,loadShop,buyItem,
      mailbox,unreadMailCount,mailboxGroups,selectedMail,mailDetailOpen,
      loadMailbox,readMail,openMailDetail,closeMailDetail,deleteMail,handleMailAction,
      startMailAutoClose,clearMailAutoClose,
      goActive,goProblemInfo,goSolved,goBoard,goBoardSize,goMessage,goError,
      openGoBoard,closeGoBoard,handleGoClick,evaluateGo,
      gridWidth,gridHeight,COL_LABELS,
      goSvgHtml,handleSvgClick,
    };
  }
}).mount("#app");
