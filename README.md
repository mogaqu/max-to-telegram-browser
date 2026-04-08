Это бот-ретранслятор из макса в телеграм, работает не через pymax, потому что за него можно отхватить бан, а через браузер с хромиумом, имитируя человека, который 24/7 сидит и читает макс, иногда переподключаясь(настоящий патриот).
сейчас у него есть несколько недостатков, а именно:
1. токен тухнет быстро
2. для хостинга на каком-то render.com - не пойдет, потому что он памяти много жрет(так как сам хромиум жрет много) и отлетает за день, а потом вовсе не работает

команды для установки зависимостей(лучше их, чем через requirements.txt, так как нужно ещё доустановить хромиум у плейврайта):


pip install playwright aiogram python-dotenv flask
python -m playwright install chromium

код для клоудфлейр воркера:

export default {
  async fetch(request) {
    const url = new URL(request.url);
    url.host = "api.telegram.org";
    url.protocol = "https:";

    const newRequest = new Request(url.toString(), {
      method: request.method,
      headers: request.headers,
      body: request.body,
    });

    return fetch(newRequest);
  },
};

формат .env:
MAX_CHAT_URL=ссылка на группу из веб версии макс
AUTH_LOCAL_STORAGE=типа {"token:... и какая-то сессия, это через f12 искать} 
TG_BOT_TOKEN=токен бота в тг
TG_CHAT_ID=-103...(айди чата в тг(смотреть через веб версию тг или там в ссылках на чат есть через десктопную версию))
TG_TOPIC_ID=(в какой именно раздел чата слать, если его убрать, то вроде просто будет кидать напрямую, так что необязателен)
TG_API_URL=ссылка на ваш клоудфлейр воркер