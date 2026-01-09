document.addEventListener('DOMContentLoaded', function() {
    // Example: Animate cards on dashboard
    let cards = document.querySelectorAll('.card');
    cards.forEach((card, idx) => {
        card.style.opacity = 0;
        setTimeout(() => {
            card.style.transition = 'opacity 0.7s';
            card.style.opacity = 1;
        }, 100 * idx);
    });
});
