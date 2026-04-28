document.addEventListener('DOMContentLoaded', () => {
    const sceneInput = document.getElementById('scene-input');
    const analyzeBtn = document.getElementById('analyze-btn');
    const loadingIndicator = document.getElementById('loading-indicator');
    const resultsContainer = document.getElementById('results-container');
    const personsGrid = document.getElementById('persons-grid');

    analyzeBtn.addEventListener('click', async () => {
        const sceneDescription = sceneInput.value.trim();
        if (!sceneDescription) {
            alert('Please enter a scene description.');
            return;
        }

        // Show loading spinner and hide previous results
        loadingIndicator.innerHTML = '<div class="spinner"></div>';
        loadingIndicator.style.display = 'block';
        resultsContainer.style.display = 'none';
        analyzeBtn.disabled = true;

        try {
            const response = await callOllamaAPI(sceneDescription);
            displayResults(response);
        } catch (error) {
            console.error('Error analyzing scene:', error);
            alert('An error occurred while analyzing the scene. Make sure Ollama is running and the model is available.');
        } finally {
            // Hide loading spinner and show results
            loadingIndicator.style.display = 'none';
            resultsContainer.style.display = 'block';
            analyzeBtn.disabled = false;
        }
    });

    function buildPrompt(description) {
        return `
        You are an expert AI safety inspector. Your task is to analyze a workplace scene description and identify safety issues.
        Your response MUST be a single, valid JSON object, with no other text or formatting.

        Analyze the new scene provided below and generate a detailed JSON report with the following exact structure:
        {
          "summary": "A concise summary of the situation and primary safety concerns.",
          "persons": [
            {
              "id": 1,
              "description": "A brief description of this person's role or actions.",
              "ppe": {
                "hardhat": "Mentioned, Not Mentioned, or Missing",
                "safety_glasses": "Mentioned, Not Mentioned, or Missing",
                "gloves": "Mentioned, Not Mentioned, or Missing",
                "safety_vest": "Mentioned, Not Mentioned, or Missing",
                "footwear": "Mentioned, Not Mentioned, or Missing"
              },
              "actions": ["A list of actions the person is performing."],
              "hazards_faced": ["A list of hazards this person is exposed to."],
              "risks": ["A list of potential risks or injuries for this person."]
            }
          ],
          "hazards_detected": ["A list of general hazards present in the overall scene."],
          "suggested_actions": ["A list of actions to mitigate the identified risks."],
          "confidence_score": "A score from 0 to 100 representing your confidence in the analysis."
        }

        IMPORTANT RULES:
        - If a piece of PPE is not mentioned, state "Not Mentioned".
        - If the scene implies PPE should be worn but isn't, state "Missing".
        - If no people are mentioned in the scene, the "persons" array MUST be empty [].
        - The number of objects in the "persons" array must exactly match the number of people in the scene.

        Analyze this new scene:
        "${description}"
        `;
    }

    async function callOllamaAPI(description) {
        const prompt = buildPrompt(description);
        console.log('Sending prompt to Ollama API:', prompt);

        const response = await fetch('http://localhost:11434/api/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                model: 'deepseek-r1:7b',
                prompt: prompt,
                stream: false,
                format: 'json'
            }),
        });

        console.log('Received response status:', response.status);
        if (!response.ok) {
            throw new Error(`API request failed with status ${response.status}`);
        }

        const data = await response.json();
        console.log('API response data:', data);

        try {
            const parsedResponse = JSON.parse(data.response);
            console.log('Parsed response:', parsedResponse);
            return parsedResponse;
        } catch (parseError) {
            console.error('Error parsing JSON from model response:', parseError);
            console.error('Raw response string:', data.response);
            throw new Error('The model did not return valid JSON.');
        }
    }

    function displayResults(data) {
        // Populate Summary Card
        const summaryEl = document.querySelector('#summary-card .card-content');
        const confidenceEl = document.querySelector('#confidence-score .score');

        if (summaryEl) {
            summaryEl.textContent = data.summary || 'No summary provided.';
        }
        if (confidenceEl) {
            const score = parseInt(data.confidence_score, 10) || 0;
            confidenceEl.textContent = `${score}%`;
            confidenceEl.className = 'score'; // Reset
            if (score < 50) {
                confidenceEl.classList.add('low');
            } else if (score < 85) {
                confidenceEl.classList.add('medium');
            } else {
                confidenceEl.classList.add('high');
            }
        }

        // Populate Person Cards
        personsGrid.innerHTML = ''; // Clear previous results
        if (data.persons && data.persons.length > 0) {
            data.persons.forEach(person => {
                const card = document.createElement('div');
                card.className = 'person-card';

                const ppeItems = Object.entries(person.ppe).map(([key, value]) => {
                    const statusClass = value.toLowerCase().replace(/ /g, '-');
                    return `<div class="ppe-item">
                                <span class="ppe-label">${key.replace(/_/g, ' ')}:</span>
                                <span class="ppe-status ppe-status-${statusClass}">${value}</span>
                            </div>`;
                }).join('');

                const createList = (items) => items && items.length > 0 ?
                    `<ul>${items.map(i => `<li>${i}</li>`).join('')}</ul>` : '<p>None specified.</p>';

                card.innerHTML = `
                    <div class="card-header">
                        <h3>Person ${person.id}</h3>
                        <p>${person.description}</p>
                    </div>
                    <div class="card-content">
                        <div class="details-section">
                            <h4>Actions</h4>
                            ${createList(person.actions)}
                        </div>
                        <div class="details-section">
                            <h4>Hazards Faced</h4>
                            ${createList(person.hazards_faced)}
                        </div>
                        <div class="details-section">
                            <h4>Potential Risks</h4>
                            ${createList(person.risks)}
                        </div>
                        <div class="details-section">
                            <h4>PPE Status</h4>
                            <div class="ppe-grid">${ppeItems}</div>
                        </div>
                    </div>
                `;
                personsGrid.appendChild(card);
            });
        } else {
            personsGrid.innerHTML = '<div class="card-content"><p>No persons were identified in the scene.</p></div>';
        }

        // Populate Hazards and Actions Cards
        const hazardsCard = document.querySelector('#hazards-card .card-content');
        const actionsCard = document.querySelector('#actions-card .card-content');
        const createList = (items) => items && items.length > 0 ?
            `<ul>${items.map(i => `<li>${i}</li>`).join('')}</ul>` : '<p>None specified.</p>';

        if (hazardsCard) {
            hazardsCard.innerHTML = createList(data.hazards_detected);
        }
        if (actionsCard) {
            actionsCard.innerHTML = createList(data.suggested_actions);
        }
    }
});
