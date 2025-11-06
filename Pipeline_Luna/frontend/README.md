# PPE Safety Monitor - Frontend Application

## Overview
Modern, responsive web application for viewing and managing PPE violation reports. Built as a Single Page Application (SPA) with vanilla JavaScript.

## Features

### 🏠 Home Dashboard
- Real-time statistics (total violations, today, this week)
- Recent violations overview
- Quick action buttons
- System features showcase

### 📹 Live Monitoring
- Instructions for running live detection
- Keyboard controls reference
- Detection settings overview
- PPE classes display

### 📊 Reports
- Searchable violation reports
- Filter by severity and date range
- Image thumbnails
- Click to view full report

### 📈 Analytics
- Violation statistics
- Safety compliance score
- Violation type breakdown
- Time distribution analysis

### ℹ️ About
- System architecture
- Technology stack
- PPE classes (14 total)
- Credits and acknowledgments

## Technology Stack

### Frontend
- **HTML5/CSS3** - Modern, responsive design
- **Vanilla JavaScript** - No frameworks, pure JS
- **Custom Router** - SPA navigation
- **REST API** - Backend integration
- **FontAwesome** - Icon library

### Design
- **Color Scheme** - Matches NLP_Luna branding
- **Responsive** - Mobile, tablet, desktop
- **Animations** - Smooth transitions
- **Cards** - Modular component design

## File Structure

```
frontend/
├── index.html              # Main HTML file
├── css/
│   └── style.css          # All styles (400+ lines)
└── js/
    ├── config.js          # API configuration & state
    ├── api.js             # API functions
    ├── router.js          # SPA router
    ├── app.js             # Application entry point
    └── pages/
        ├── home.js        # Home dashboard
        ├── live.js        # Live monitoring
        ├── reports.js     # Reports list
        ├── analytics.js   # Analytics dashboard
        └── about.js       # About page
```

## API Endpoints

### GET /api/violations
Returns all violations in JSON format.

**Response:**
```json
[
  {
    "report_id": "20251105_215050",
    "timestamp": "2025-11-05T21:50:50",
    "has_original": true,
    "has_annotated": true,
    "has_report": false
  }
]
```

### GET /report/{report_id}
View individual report (HTML page).

### GET /image/{report_id}/{filename}
Get violation images (original.jpg or annotated.jpg).

## How to Run

### Option 1: Batch File (Recommended)
```bash
run_frontend.bat
```

### Option 2: Python Command
```bash
python view_reports.py
```

### Option 3: Virtual Environment
```bash
.venv\Scripts\activate
python view_reports.py
```

Then open browser to: **http://localhost:5001**

## Development

### Adding a New Page

1. **Create page component** in `js/pages/yourpage.js`:
```javascript
const YourPage = {
    render() {
        return `<div class="page">Your HTML here</div>`;
    },
    
    async mount() {
        // Load data, attach events, etc.
    }
};
```

2. **Register route** in `js/app.js`:
```javascript
Router.register('yourpage', YourPage);
```

3. **Add navigation link** in `index.html`:
```html
<li><a href="#yourpage" class="nav-link" data-page="yourpage">
    <i class="fas fa-icon"></i> Your Page
</a></li>
```

### Styling Guidelines

Use CSS variables defined in `style.css`:
```css
var(--primary-color)      /* #2c3e50 - Dark blue */
var(--secondary-color)    /* #3498db - Blue */
var(--success-color)      /* #2ecc71 - Green */
var(--warning-color)      /* #f39c12 - Orange */
var(--error-color)        /* #e74c3c - Red */
```

### Component Classes

Available reusable classes:
- `.card` - Card container
- `.card-header` - Card header
- `.card-content` - Card content
- `.btn`, `.btn-primary`, `.btn-success`, etc. - Buttons
- `.badge`, `.badge-success`, etc. - Badges
- `.stat-card` - Statistics card
- `.grid`, `.grid-2`, `.grid-3`, `.grid-4` - Grid layouts
- `.alert`, `.alert-info`, etc. - Alert messages

## Browser Compatibility

- ✅ Chrome 90+
- ✅ Firefox 88+
- ✅ Edge 90+
- ✅ Safari 14+

## Features Roadmap

### Current (v1.0)
- [x] Home dashboard
- [x] Live monitoring guide
- [x] Reports viewing
- [x] Analytics dashboard
- [x] About page
- [x] REST API integration

### Planned (v1.1)
- [ ] WebSocket for real-time updates
- [ ] Live video stream embed
- [ ] Chart.js integration for analytics
- [ ] PDF report download
- [ ] Dark mode toggle
- [ ] User authentication

### Future (v2.0)
- [ ] React/Vue.js migration
- [ ] Advanced filtering
- [ ] Export to CSV
- [ ] Multi-camera support
- [ ] Custom alert rules
- [ ] Email notifications

## Customization

### Change Color Scheme
Edit `frontend/css/style.css`:
```css
:root {
    --primary-color: #yourcolor;
    --secondary-color: #yourcolor;
    /* ... */
}
```

### Change API Endpoint
Edit `frontend/js/config.js`:
```javascript
const API_CONFIG = {
    BASE_URL: 'http://your-server:port',
    /* ... */
};
```

## Performance

- **Load Time:** < 1 second (local)
- **File Size:** ~150KB total (unminified)
- **API Calls:** Lazy loaded per page
- **Images:** Lazy loaded on demand

## Security

- CORS enabled for localhost
- No sensitive data in frontend
- Images served with content-type validation
- Path traversal protection

## Troubleshooting

### Backend Not Detected
**Problem:** Warning banner appears  
**Solution:** Start backend server: `python view_reports.py`

### Images Not Loading
**Problem:** 404 errors for images  
**Solution:** Check violations directory exists and contains reports

### Blank Page
**Problem:** Page doesn't load  
**Solution:** Check browser console for JavaScript errors

### Styling Issues
**Problem:** CSS not applied  
**Solution:** Clear browser cache, hard refresh (Ctrl+F5)

## Credits

Built with:
- [FontAwesome](https://fontawesome.com/) - Icons
- [Google Fonts](https://fonts.google.com/) - Inter font
- Vanilla JavaScript - No dependencies!

## License

Part of FYP Combined project.

## Support

For issues or questions, check:
1. Browser console for errors
2. Network tab for API calls
3. Backend server logs

---

**Enjoy the modern PPE Safety Monitor frontend! 🎉**
