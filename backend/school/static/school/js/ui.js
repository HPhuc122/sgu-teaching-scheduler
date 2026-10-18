(() => {
  'use strict';
  const body = document.body;
  const sidebar = document.getElementById('uiSidebar');
  const menu = document.getElementById('uiMenuToggle');
  const backdrop = document.getElementById('uiBackdrop');
  const mobile = window.matchMedia('(max-width: 1000px)');
  const storage = {
    get(key) { try { return localStorage.getItem(key); } catch (_) { return null; } },
    set(key, value) { try { localStorage.setItem(key, value); } catch (_) {} },
  };
  // Django creates its searchable selectors on window.load. Only localize text;
  // preserve all controls, option values and built-in selection event handlers.
  window.addEventListener('load', () => {
    document.querySelectorAll('.selector').forEach(selector => {
      const available = selector.querySelector('.selector-available');
      const chosen = selector.querySelector('.selector-chosen');
      const isGroup = Boolean(selector.querySelector('select[name=groups],select[name=groups_old]'));
      const unit = isGroup ? 'nhóm' : 'quyền';
      const availableTitle = available?.querySelector('.selector-available-title label');
      const chosenTitle = chosen?.querySelector('.selector-chosen-title label');
      if (availableTitle) availableTitle.textContent = isGroup ? 'Nhóm có thể chọn' : 'Quyền có thể chọn';
      if (chosenTitle) chosenTitle.textContent = isGroup ? 'Nhóm đã chọn' : 'Quyền đã chọn';
      const availableHelp = available?.querySelector('.helptext');
      const chosenHelp = chosen?.querySelector('.helptext');
      if (availableHelp) availableHelp.textContent = 'Tìm kiếm, chọn các mục rồi nhấn mũi tên để thêm.';
      if (chosenHelp) chosenHelp.textContent = 'Chọn các mục rồi nhấn mũi tên để bỏ chọn.';
      const addAll = selector.querySelector('.selector-chooseall');
      const removeAll = selector.querySelector('.selector-clearall');
      if (addAll) addAll.textContent = 'Chọn tất cả ' + unit;
      if (removeAll) removeAll.textContent = 'Bỏ chọn tất cả ' + unit;
      for (const [area, state] of [[available,'có thể chọn'], [chosen,'đã chọn']]) {
        const search = area?.querySelector('.selector-filter input');
        if (search) { search.placeholder = 'Tìm ' + unit + '…'; search.setAttribute('aria-label', `Tìm ${unit} ${state}`); }
      }
    });
  });
  if (storage.get('sgu-nav-collapsed') === 'true') body.classList.add('nav-collapsed');
  function syncNav() {
    const open = mobile.matches ? body.classList.contains('nav-open') : !body.classList.contains('nav-collapsed');
    if (menu) {
      menu.setAttribute('aria-expanded', String(open));
      menu.setAttribute('aria-label', open ? 'Thu gọn thanh điều hướng' : 'Mở thanh điều hướng');
    }
    if (backdrop) backdrop.hidden = !(mobile.matches && open);
    if (sidebar) sidebar.inert = mobile.matches && !open;
  }
  function closeNav() { body.classList.remove('nav-open'); syncNav(); }
  menu?.addEventListener('click', () => {
    if (mobile.matches) body.classList.toggle('nav-open');
    else { body.classList.toggle('nav-collapsed'); storage.set('sgu-nav-collapsed', String(body.classList.contains('nav-collapsed'))); }
    syncNav();
    if (mobile.matches && body.classList.contains('nav-open')) sidebar?.querySelector('a')?.focus();
  });
  backdrop?.addEventListener('click', () => { closeNav(); menu?.focus(); });
  mobile.addEventListener('change', closeNav);
  syncNav();
  // Keep focus inside the mobile navigation while its backdrop is open.
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      if (body.classList.contains('nav-open')) { closeNav(); menu?.focus(); }
      const account = document.querySelector('.ui-account[open]');
      if (account) { account.open = false; account.querySelector('summary').focus(); }
    }
    if (event.key === 'Tab' && mobile.matches && body.classList.contains('nav-open')) {
      const links = [...sidebar.querySelectorAll('a[href]')];
      if (event.shiftKey && document.activeElement === links[0]) { event.preventDefault(); links.at(-1)?.focus(); }
      else if (!event.shiftKey && document.activeElement === links.at(-1)) { event.preventDefault(); links[0]?.focus(); }
    }
  });
  let bestLink;
  document.querySelectorAll('.ui-sidebar nav a').forEach(link => {
    if (location.pathname === link.pathname || (link.pathname !== '/admin/' && location.pathname.startsWith(link.pathname))) {
      if (!bestLink || link.pathname.length > bestLink.pathname.length) bestLink = link;
    }
  });
  if (!bestLink && location.pathname.includes('/admin/import-catalog/')) bestLink = document.querySelector('.ui-sidebar a[href$="/import-catalog/courses/"]');
  if (bestLink) { bestLink.classList.add('active'); bestLink.setAttribute('aria-current', 'page'); }
  const pageTitle = document.querySelector('main h1');
  if (pageTitle && document.getElementById('uiPageTitle')) document.getElementById('uiPageTitle').textContent = pageTitle.textContent;
  const themeToggle = document.getElementById('uiThemeToggle');
  function syncTheme() {
    const dark = document.documentElement.dataset.theme === 'dark';
    themeToggle?.setAttribute('aria-pressed', String(dark));
    themeToggle?.setAttribute('aria-label', dark ? 'Bật giao diện sáng' : 'Bật giao diện tối');
  }
  themeToggle?.addEventListener('click', () => {
    const theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = theme;
    storage.set('uctp-theme', theme);
    syncTheme();
  });
  syncTheme();
  document.querySelectorAll('[data-reset-lecturer]').forEach(select => {
    select.addEventListener('change', () => {
      const lecturer = document.getElementById('lecturer');
      const choices = document.getElementById('lecturerChoices');
      if (lecturer) {
        lecturer.replaceChildren(lecturer.options[0].cloneNode(true));
        choices?.content.querySelectorAll('option').forEach(option => {
          if (!select.value || option.dataset.faculty === select.value) lecturer.append(option.cloneNode(true));
        });
        lecturer.value = '';
      }
      // Keep explicit filter submission so users can finish other fields first.
    });
  });
  const semesterSelect = document.querySelector('#scheduleUploadForm #semester');
  const semesterConfig = document.getElementById('semesterConfig');
  function showSemesterConfig() {
    const option = semesterSelect?.selectedOptions[0];
    if (!semesterConfig) return;
    semesterConfig.textContent = option?.dataset.weeks
      ? `${option.dataset.weeks} tuần học · Từ ${option.dataset.start} đến ${option.dataset.end}`
      : 'Chọn học kỳ để xem số tuần và thời gian đào tạo.';
  }
  semesterSelect?.addEventListener('change', showSemesterConfig);
  showSemesterConfig();
  document.addEventListener('click', event => {
    const account = document.querySelector('.ui-account[open]');
    if (account && !account.contains(event.target)) account.open = false;
  });
  document.querySelectorAll('input[type=file]').forEach(input => {
    const feedback = document.createElement('small');
    feedback.className = 'file-feedback'; feedback.setAttribute('aria-live', 'polite');
    input.after(feedback);
    input.addEventListener('change', () => {
      const file = input.files[0];
      feedback.textContent = file ? `Đã chọn: ${file.name} (${(file.size / 1024).toFixed(0)} KB)` : '';
    });
  });
  // Wrap wide tables without rebuilding Django's form controls or widget markup.
  document.querySelectorAll('.custom-page main table').forEach(table => {
    if (!table.closest('.table-wrap')) { const wrap = document.createElement('div'); wrap.className = 'table-wrap'; table.before(wrap); wrap.append(table); }
  });
  document.querySelectorAll('.table-wrap,.results').forEach(wrap => {
    wrap.tabIndex = 0; wrap.setAttribute('role', 'region');
    wrap.setAttribute('aria-label', 'Bảng dữ liệu, cuộn ngang để xem thêm');
  });
  document.querySelectorAll('.error,.auth-error,.errornote').forEach(error => error.setAttribute('role', 'alert'));
  document.querySelectorAll('.success,.message:not(.error),.result').forEach(message => message.setAttribute('role', 'status'));
  // Only explicit long-running custom forms get a busy state; preserve submitter values.
  document.querySelectorAll('form[data-busy]').forEach(form => {
    form.addEventListener('submit', event => {
      if (form.dataset.submitting) { event.preventDefault(); return; }
      form.dataset.submitting = 'true'; form.setAttribute('aria-busy', 'true');
      const button = event.submitter;
      if (button) { button.textContent = form.dataset.busy; button.setAttribute('aria-disabled', 'true'); }
    });
  });
  const approval = document.querySelector('form.approve');
  if (approval) {
    const choices = [...approval.querySelectorAll('input[name=entry_ids]')];
    const submit = approval.querySelector('button[type=submit]');
    const count = document.getElementById('selectionCount');
    const all = document.getElementById('selectAllEntries');
    function update() {
      const selected = choices.filter(input => input.checked).length;
      if (submit && submit.dataset.locked !== 'true') submit.disabled = selected === 0;
      if (count) count.textContent = `Đã chọn ${selected} buổi trên trang này`;
      if (all) { all.checked = choices.length > 0 && selected === choices.length; all.indeterminate = selected > 0 && selected < choices.length; }
    }
    all?.addEventListener('change', () => { choices.forEach(input => { input.checked = all.checked; }); update(); });
    choices.forEach(input => input.addEventListener('change', update)); update();
  }
  // BFCache restores the original form state after Back, rather than leaving it busy.
  window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
})();
