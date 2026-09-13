
(() => {
  const state = {
    data:null, category:null, difficulty:"Scared",
    roundPairs:[], selectedQ:null, selectedA:null,
    matched:0, attempts:0, score:0
  };

  const $ = s => document.querySelector(s);
  const categorySelect = $("#category");
  const difficultySelect = $("#difficulty");
  const startBtn = $("#startBtn");
  const setup = $("#setup");
  const game = $("#game");
  const errorBox = $("#errorBox");
  const qCol = $("#questions");
  const aCol = $("#answers");
  const categoryName = $("#categoryName");
  const difficultyName = $("#difficultyName");
  const matchStat = $("#matchStat");
  const scoreStat = $("#scoreStat");
  const complete = $("#complete");

  function shuffle(arr){
    const a=[...arr];
    for(let i=a.length-1;i>0;i--){
      const j=Math.floor(Math.random()*(i+1));
      [a[i],a[j]]=[a[j],a[i]];
    }
    return a;
  }

  function difficultySlice(list, difficulty){
    if(list.length===52){
      if(difficulty==="Scared") return list.slice(0,18);
      if(difficulty==="Curious") return list.slice(18,35);
      return list.slice(35,52);
    }
    if(difficulty==="Scared") return list.slice(0,17);
    if(difficulty==="Curious") return list.slice(17,34);
    return list.slice(34,51);
  }

  function setError(msg){
    errorBox.textContent=msg;
    errorBox.classList.toggle("hidden",!msg);
  }

  async function loadData(){
    try{
      const r=await fetch("data/master666.json",{cache:"no-store"});
      if(!r.ok) throw new Error("Could not load Master 666");
      state.data=await r.json();
      Object.keys(state.data.categories).forEach(name=>{
        const o=document.createElement("option");
        o.value=name; o.textContent=name;
        categorySelect.appendChild(o);
      });
      startBtn.disabled=false;
      setError("");
    }catch(err){
      setError("Master 666 failed to load. " + err.message);
    }
  }

  function renderRound(){
    qCol.innerHTML="";
    aCol.innerHTML="";
    complete.classList.add("hidden");
    state.selectedQ=null; state.selectedA=null;
    state.matched=0; state.attempts=0;
    updateStats();

    const questions=state.roundPairs.map((p,i)=>({id:i,text:p.question}));
    const answers=shuffle(state.roundPairs.map((p,i)=>({id:i,text:p.answer})));

    questions.forEach(item=>qCol.appendChild(makeButton(item,"q")));
    answers.forEach(item=>aCol.appendChild(makeButton(item,"a")));
  }

  function makeButton(item,type){
    const b=document.createElement("button");
    b.className="match-btn";
    b.type="button";
    b.textContent=item.text;
    b.dataset.id=item.id;
    b.dataset.type=type;
    b.addEventListener("click",()=>selectButton(b,type,item.id));
    return b;
  }

  function selectButton(btn,type,id){
    if(btn.classList.contains("matched")) return;
    const col=type==="q"?qCol:aCol;
    col.querySelectorAll(".selected").forEach(x=>x.classList.remove("selected"));
    btn.classList.add("selected");
    if(type==="q") state.selectedQ={btn,id};
    else state.selectedA={btn,id};
    if(state.selectedQ && state.selectedA) checkMatch();
  }

  function checkMatch(){
    const q=state.selectedQ, a=state.selectedA;
    state.attempts++;
    if(q.id===a.id){
      q.btn.classList.remove("selected"); a.btn.classList.remove("selected");
      q.btn.classList.add("correct"); a.btn.classList.add("correct");
      setTimeout(()=>{
        q.btn.classList.add("matched"); a.btn.classList.add("matched");
        q.btn.classList.remove("correct"); a.btn.classList.remove("correct");
      },220);
      state.matched++;
      state.score += 100;
      state.selectedQ=null; state.selectedA=null;
      updateStats();
      if(state.matched===state.roundPairs.length){
        setTimeout(()=>complete.classList.remove("hidden"),260);
      }
    }else{
      state.score=Math.max(0,state.score-20);
      q.btn.classList.add("wrong"); a.btn.classList.add("wrong");
      setTimeout(()=>{
        q.btn.classList.remove("wrong","selected");
        a.btn.classList.remove("wrong","selected");
        state.selectedQ=null; state.selectedA=null;
      },420);
      updateStats();
    }
  }

  function updateStats(){
    matchStat.textContent=`${state.matched}/${state.roundPairs.length || 6} matched`;
    scoreStat.textContent=`Score ${state.score}`;
  }

  function newRound(){
    const full=state.data.categories[state.category];
    const pool=difficultySlice(full,state.difficulty);
    state.roundPairs=shuffle(pool).slice(0,Math.min(6,pool.length));
    renderRound();
  }

  function startGame(){
    if(!state.data) return;
    state.category=categorySelect.value;
    state.difficulty=difficultySelect.value;
    state.score=0;
    categoryName.textContent=state.category;
    difficultyName.textContent=state.difficulty;
    setup.classList.add("hidden");
    game.classList.remove("hidden");
    newRound();
  }

  startBtn.addEventListener("click",startGame);
  $("#newRoundBtn").addEventListener("click",newRound);
  $("#homeBtn").addEventListener("click",()=>{
    game.classList.add("hidden");
    setup.classList.remove("hidden");
    complete.classList.add("hidden");
  });

  loadData();
})();
