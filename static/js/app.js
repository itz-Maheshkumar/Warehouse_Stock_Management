document.addEventListener('DOMContentLoaded', function(){
  const pageTitle = document.title || 'CatParts Application';
  const sidebar = document.getElementById('sidebar');
  const toggle = document.getElementById('sidebarToggle');
  const closeButton = document.getElementById('sidebarClose');
  const backdrop = document.getElementById('sidebarBackdrop');

  function uiLog(message, metadata = {}) {
    console.info(`[CatParts] ${message}`, metadata);
  }

  function setSidebarOpen(open) {
    if (!sidebar) {
      return;
    }

    if (open) {
      document.body.classList.add('sidebar-open');
      sidebar.classList.remove('d-none');
    } else {
      document.body.classList.remove('sidebar-open');
      sidebar.classList.add('d-none');
    }
  }

  uiLog('UI initialized', { page: pageTitle, path: window.location.pathname });

  if (toggle && sidebar) {
    const savedHidden = localStorage.getItem('catpartsSidebarHidden');
    if (savedHidden === 'true') {
      setSidebarOpen(false);
    } else {
      setSidebarOpen(true);
    }

    toggle.addEventListener('click', function(e){
      e.preventDefault();
      const isHidden = sidebar.classList.contains('d-none');
      setSidebarOpen(isHidden);
      localStorage.setItem('catpartsSidebarHidden', isHidden ? 'false' : 'true');
      uiLog('Sidebar toggled', { open: isHidden });
    });
  }

  if (closeButton) {
    closeButton.addEventListener('click', function(e){
      e.preventDefault();
      setSidebarOpen(false);
      localStorage.setItem('catpartsSidebarHidden', 'true');
      uiLog('Sidebar closed', {});
    });
  }

  if (backdrop) {
    backdrop.addEventListener('click', function(){
      setSidebarOpen(false);
      uiLog('Sidebar backdrop clicked', {});
    });
  }
});
