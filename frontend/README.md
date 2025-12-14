# Docify Frontend - PWA Setup Instructions

## 🚀 Quick Start

The frontend is configured as a Progressive Web App (PWA) with offline support and mobile optimization.

### Install Dependencies

```bash
cd frontend
npm install
```

### Start Development Server

```bash
npm run dev
```

The app will be available at:
- **Local**: http://localhost:3000
- **Network**: http://YOUR_IP:3000 (accessible from mobile devices on same network)

### Build for Production

```bash
npm run build
npm run preview
```

## 📱 PWA Features

### Offline Support
- Service worker caches app shell and assets
- API responses cached with NetworkFirst strategy
- Works offline after first visit

### Mobile Optimized
- Responsive design for all screen sizes
- Touch-friendly UI (44px minimum touch targets)
- Safe area support for notched devices (iPhone X+)
- Installable as native app on mobile devices

### Network Access
The dev server is configured to listen on `0.0.0.0:3000`, making it accessible from:
- Your computer: http://localhost:3000
- Mobile on same network: http://YOUR_IP_ADDRESS:3000

**Find your IP address:**
```bash
# macOS/Linux
ifconfig | grep "inet " | grep -v 127.0.0.1

# Or use
hostname -I
```

## 🔧 Configuration

### Vite Config (`vite.config.ts`)
- PWA plugin with service worker
- Offline caching strategy
- API proxy to backend
- Network host binding (0.0.0.0)

### PWA Manifest
Auto-generated manifest includes:
- App name: "Docify - AI Second Brain"
- Theme color: Dark mode (#1f2937)
- Display: Standalone (full-screen app)
- Icons: 192x192 and 512x512

### Service Worker
- Caches static assets (JS, CSS, HTML, images)
- NetworkFirst strategy for API calls
- 24-hour cache expiration
- Auto-update on new version

## 📲 Installing on Mobile

### iOS (Safari)
1. Open http://YOUR_IP:3000 in Safari
2. Tap the Share button
3. Tap "Add to Home Screen"
4. Tap "Add"

### Android (Chrome)
1. Open http://YOUR_IP:3000 in Chrome
2. Tap the menu (three dots)
3. Tap "Install app" or "Add to Home Screen"
4. Tap "Install"

## 🎨 Tech Stack

- **React 18** - UI framework
- **TypeScript** - Type safety
- **Vite** - Build tool and dev server
- **Tailwind CSS** - Utility-first styling
- **vite-plugin-pwa** - PWA support
- **Workbox** - Service worker library

## 📁 Project Structure

```
frontend/
├── public/              # Static assets
├── src/
│   ├── components/      # Reusable UI components
│   ├── pages/           # Page components
│   ├── services/        # API clients
│   ├── hooks/           # Custom React hooks
│   ├── utils/           # Helper functions
│   ├── assets/          # Images, fonts, etc.
│   ├── App.tsx          # Main app component
│   ├── main.tsx         # Entry point with PWA registration
│   └── index.css        # Global styles
├── index.html           # HTML template
├── vite.config.ts       # Vite + PWA configuration
├── tailwind.config.js   # Tailwind CSS config
└── package.json         # Dependencies
```

## 🧪 Testing

### Test on Mobile Device

1. Start backend: `docker-compose up -d`
2. Start frontend: `cd frontend && npm run dev`
3. Find your IP: `ifconfig | grep "inet "`
4. On mobile, open: `http://YOUR_IP:3000`
5. Test offline: Enable airplane mode, app should still work

### Test PWA Installation

1. Open in Chrome/Safari
2. Look for install prompt
3. Install app
4. Open from home screen
5. Should work like native app

## 🔍 Debugging

### Check Service Worker
1. Open DevTools (F12)
2. Go to Application tab
3. Click "Service Workers"
4. Should see registered worker

### Check Cache
1. Open DevTools
2. Go to Application > Cache Storage
3. Should see cached assets

### Network Status
The app shows two status indicators:
- **Network**: Online/Offline (internet connection)
- **API**: Backend connectivity status

## 🚨 Troubleshooting

### Can't access from mobile
- Check firewall settings
- Ensure mobile is on same WiFi network
- Try disabling VPN
- Use IP address, not localhost

### Service worker not registering
- Must use HTTPS or localhost
- Check browser console for errors
- Clear cache and reload

### App not installable
- Must be served over HTTPS (or localhost)
- Manifest must be valid
- Service worker must be registered

## 📝 Next Steps

1. **Install dependencies**: `npm install`
2. **Start dev server**: `npm run dev`
3. **Test on mobile**: Open http://YOUR_IP:3000
4. **Install as PWA**: Use browser's install prompt
5. **Build components**: Add upload, search, chat features

## 🎯 Development Workflow

```bash
# Install dependencies
npm install

# Start dev server (with hot reload)
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview

# Lint code
npm run lint
```

