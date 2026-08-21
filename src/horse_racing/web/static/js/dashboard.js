const filterForm = document.querySelector("[data-filter-form]");

if (filterForm) {
  filterForm.querySelectorAll("select").forEach((select) => {
    select.addEventListener("change", () => filterForm.requestSubmit());
  });
}

document.querySelectorAll("[data-href]").forEach((row) => {
  const navigate = () => {
    window.location.href = row.dataset.href;
  };

  row.addEventListener("click", navigate);
  row.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      navigate();
    }
  });
});
