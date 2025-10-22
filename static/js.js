const deletionModal = new bootstrap.Modal(document.getElementById('deletionModal'));
let whatpost = -1;

function linkifyMentions() {
    const mentionRegex = /\/u\/[\w-]+(?=\W|$)/g;
    const postTitles = document.querySelectorAll('.postTitle');
    postTitles.forEach(postTitle => {
        postTitle.innerHTML = postTitle.textContent.replace(mentionRegex, match => {
            return `<a class="text-decoration-none text-danger" href="${match}">${match}</a>`;
        });
    });
}

document.addEventListener('DOMContentLoaded', linkifyMentions);
const socket = io();
socket.on('flr_change_rating', data => {
    window.location.href = '/u/';
})
function toggleMenu() {
    document.getElementById("sidebar").classList.toggle("active");
}

function submitDeletePost() {
    if (whatpost !== -1) {
        document.getElementById(`removePost_${whatpost}`).submit();
    }
}

async function copyLink(event) {
    const clickedElement = event.target;
    const parentElement = clickedElement.parentElement.parentElement;
    const parentId = parentElement.parentElement.getAttribute('data-post-id');
    let copyOverlay = document.getElementById('copyToast');
    copyOverlay.style.display = "block";
    try {
        await navigator.clipboard.writeText(window.location.href.match(/http[s]*:\/\/[0-9a-zA-Z-.:]+/) + '/p/' + parentId);
        copyOverlay.innerText = 'Text copied to clipboard!';
    } catch (err) {
        console.error('Failed to copy text: ', err);
        copyOverlay.innerText = 'Failed to copy text';
    }
    setTimeout(() => {
        copyOverlay.style.display = "none";
    }, 2000);
}

function send_change_rating(event) {
    const clickedElement = event.target.parentElement;
    const parentEle = clickedElement.parentElement;
    const parentId = parentEle.parentElement.getAttribute('data-post-id');
    let what;
    if (clickedElement.id === "like-button") {
        if (clickedElement.className === 'enabled-span') {
            what = 1;
        } else if (clickedElement.className === 'disabled-span') {
            what = 2;
        } else if (clickedElement.className === 'disabled-span-clicked') {
            what = -1;
        }
    } else if (clickedElement.id === "dislike-button") {
        if (clickedElement.className === 'enabled-span') {
            what = -1;
        } else if (clickedElement.className === 'disabled-span') {
            what = -2;
        } else if (clickedElement.className === 'disabled-span-clicked') {
            what = 1;
        }
    }
    socket.emit('change_rating', {postId: parentId, what: what, clickedElementId: clickedElement.id});
}