// Run with: node test_chat_input.cjs. Exercises the actual inline submission handler.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(`${__dirname}/news-first.html`, 'utf8');
const handler = html.slice(html.indexOf('async function sendChat(event){'), html.indexOf('\nfunction feed(){'));

async function check(outcome) {
  const elements = Object.fromEntries(['chat-input', 'chat-send', 'chat-error', 'chat-status', 'chat-log']
    .map(id => [id, {value: '', disabled: false, textContent: '', focus() {}}]));
  elements['chat-input'].value = 'Why XOM?';
  let finish, fail, submitted;
  const pending = new Promise((resolve, reject) => { finish = resolve; fail = reject; });
  const messages = [];
  const context = vm.createContext({
    AbortController, result: {}, chatController: null, chatMessages: [],
    selected: {id: 'test'}, days: 5, comparisons: [], removedTickers: new Set(), lineColours: {}, profile: null,
    $: id => elements[id],
    chatMessage: (role, text) => { messages.push({role, text}); return {body: {textContent: text}}; },
    chartWindow: () => ({start: 0, end: 1}), chatPrices: () => [],
    readStream: async (url, body, signal, consume) => {
      submitted = body;
      await pending;
      consume({type: 'delta', text: 'Oil exposure.'});
    }
  });
  vm.runInContext(handler, context);
  const request = context.sendChat({preventDefault() {}});
  assert.equal(elements['chat-input'].value, '', 'Clear the input while the response is still pending');
  assert.equal(elements['chat-input'].disabled, true);
  assert.equal(messages[0].text, 'Why XOM?');
  assert.equal(submitted.messages.at(-1).content, 'Why XOM?', 'Clearing must not change the submitted question');
  if (outcome === 'cancel') {
    context.chatController = null;
    elements['chat-input'].value = 'New story question';
  }
  if (outcome === 'success') finish(); else fail(Error('Test failure'));
  await request;
  assert.equal(elements['chat-input'].value,
    outcome === 'success' ? '' : outcome === 'failure' ? 'Why XOM?' : 'New story question');
  assert.equal(context.chatMessages.length, outcome === 'success' ? 2 : 0);
  if (outcome !== 'cancel') assert.equal(elements['chat-input'].disabled, false);
}

(async () => {
  for (const outcome of ['success', 'failure', 'cancel']) await check(outcome);
  console.log('Chat input submission checks passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
