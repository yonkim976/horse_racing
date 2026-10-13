(() => {
  'use strict';
  const dialog = document.getElementById('feedback-dialog');
  const launchers = document.querySelectorAll('[data-feedback-open]');
  if (!dialog || !launchers.length) return;
  const form = dialog.querySelector('[data-feedback-form]');
  const message = form.elements.message;
  const success = dialog.querySelector('[data-feedback-success]');
  const submit = form.querySelector('[type="submit"]');
  const error = dialog.querySelector('[data-feedback-error]');
  let pending = false;
  let requestId = null;
  let previousPayload = null;
  // Attach only public route/filter context, never arbitrary searches or fragments.
  const current = new URL(window.location.href);
  const context = new URLSearchParams();
  for (const key of ['race_id', 'date', 'meet', 'tab', 'distance', 'year', 'period']) {
    const value = current.searchParams.get(key);
    if (value && /^[a-zA-Z0-9_-]{1,32}$/.test(value)) context.set(key, value);
  }
  const title = document.body.classList.contains('mobile-app')
    ? document.querySelector('main h1')?.textContent.trim() || document.title
    : document.title.replace(/\s*·\s*마필로그.*$/, '');
  dialog.querySelector('[data-feedback-page-title]').textContent = title;
  dialog.querySelector('[data-feedback-page-path]').textContent = current.pathname + (context.size ? `?${context}` : '');

  launchers.forEach(launcher => {
    launcher.addEventListener('click', () => {
      if (!dialog.open) dialog.showModal();
    });
  });
  dialog.querySelectorAll('[data-feedback-close]').forEach(button => {
    button.addEventListener('click', () => dialog.close());
  });
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const box = dialog.getBoundingClientRect();
    if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close();
  });
  message.addEventListener('input', () => {
    message.setCustomValidity('');
    dialog.querySelector('[data-feedback-count]').textContent = `${message.value.length.toLocaleString('ko-KR')} / 1,000`;
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (pending) return;
    message.setCustomValidity(message.value.trim().length < 10 ? '의견을 10자 이상 작성해 주세요.' : '');
    if (!form.reportValidity()) return;
    const payload = {
      category: form.elements['feedback-type'].value,
      message: message.value.trim(),
      email: form.elements.email.value.trim() || null,
      page_path: form.elements['include-page'].checked
        ? dialog.querySelector('[data-feedback-page-path]').textContent : null,
      website: form.elements.website.value,
    };
    const serialized = JSON.stringify(payload);
    if (serialized !== previousPayload || !requestId) {
      requestId = crypto.randomUUID();
      previousPayload = serialized;
    }
    pending = true;
    submit.disabled = true;
    submit.setAttribute('aria-busy', 'true');
    error.hidden = true;
    try {
      const tokenResponse = await fetch('/api/feedback/token', {
        cache: 'no-store', credentials: 'same-origin', signal: AbortSignal.timeout(10000),
      });
      const tokenResult = await tokenResponse.json();
      if (!tokenResponse.ok || !tokenResult.token) throw new Error(tokenResult.message || '의견 접수를 잠시 사용할 수 없습니다.');
      const resultResponse = await fetch('/api/feedback', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: {'Content-Type': 'application/json', 'X-Feedback-Token': tokenResult.token},
        body: JSON.stringify({...payload, request_id: requestId}),
        signal: AbortSignal.timeout(15000),
      });
      const result = await resultResponse.json();
      if (!resultResponse.ok || !result.ok) throw new Error(result.message || '접수하지 못했습니다. 다시 시도해 주세요.');
      dialog.querySelector('[data-feedback-result-type]').textContent = payload.category;
      dialog.querySelector('[data-feedback-result-message]').textContent = payload.message;
      dialog.querySelector('[data-feedback-reference]').textContent = `접수번호 ${result.reference.slice(0, 8).toUpperCase()}`;
      form.hidden = true;
      success.hidden = false;
      success.focus();
    } catch (failure) {
      error.textContent = failure.name === 'Error' ? failure.message : '접수 결과를 확인하지 못했습니다. 내용은 유지되니 다시 보내 주세요.';
      error.hidden = false;
    } finally {
      pending = false;
      submit.disabled = false;
      submit.removeAttribute('aria-busy');
    }
  });
  submit.disabled = false;
  dialog.addEventListener('close', () => {
    if (!success.hidden) {
      form.reset();
      requestId = null;
      previousPayload = null;
      dialog.querySelector('[data-feedback-count]').textContent = '0 / 1,000';
      dialog.querySelector('[data-feedback-result-message]').textContent = '';
      success.hidden = true;
      form.hidden = false;
    }
  });
})();
